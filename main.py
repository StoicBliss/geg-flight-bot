import os
import logging
import threading
import time
from datetime import datetime, timedelta
import pytz
import requests
import pandas as pd
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# -----------------------------------------------------------------------------
# CONFIGURATION & ENV VARS
# -----------------------------------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AVIATIONSTACK_KEY = os.getenv("AVIATIONSTACK_KEY")
OPENWEATHER_KEY = os.getenv("OPENWEATHER_KEY")

# Spokane Airport IATA
AIRPORT_IATA = "GEG"

# Timezone
TZ_PACIFIC = pytz.timezone('US/Pacific')

# Caching Configuration
CACHE_DURATION_MINUTES = 240
data_cache = {
    "arrivals": {"data": None, "timestamp": None},
    "departures": {"data": None, "timestamp": None},
    "weather": {"data": None, "timestamp": None}
}

# Logging Setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# FLASK KEEP-ALIVE SERVER
# -----------------------------------------------------------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "GEG Rideshare Bot is Running!"

def run_flask():
    # standard Render port is often 10000, or defined by PORT env
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

def start_keep_alive():
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()

# -----------------------------------------------------------------------------
# CORE LOGIC & DATA FETCHING
# -----------------------------------------------------------------------------

def get_current_pacific_time():
    return datetime.now(TZ_PACIFIC)

def fetch_weather():
    """Fetches weather for Spokane International Airport."""
    cache_entry = data_cache["weather"]
    now = get_current_pacific_time()

    # Check Cache
    if cache_entry["data"] and cache_entry["timestamp"]:
        if (now - cache_entry["timestamp"]).total_seconds() < (CACHE_DURATION_MINUTES * 60):
            return cache_entry["data"]

    url = f"https://api.openweathermap.org/data/2.5/weather?lat=47.62&lon=-117.53&appid={OPENWEATHER_KEY}&units=imperial"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        weather_info = {
            "temp": round(data["main"]["temp"]),
            "desc": data["weather"][0]["description"].title(),
            "wind": round(data["wind"]["speed"])
        }
        
        # Update Cache
        data_cache["weather"] = {"data": weather_info, "timestamp": now}
        return weather_info
    except Exception as e:
        logger.error(f"Weather API Error: {e}")
        return None

def fetch_flights(mode="arrival"):
    """
    Fetches flight data from AviationStack.
    mode: 'arrival' or 'departure'
    """
    cache_key = "arrivals" if mode == "arrival" else "departures"
    cache_entry = data_cache[cache_key]
    now = get_current_pacific_time()

    # Check Cache
    if cache_entry["data"] is not None and cache_entry["timestamp"]:
        if (now - cache_entry["timestamp"]).total_seconds() < (CACHE_DURATION_MINUTES * 60):
            logger.info(f"Returning cached {mode} data.")
            return cache_entry["data"]

    # Build Params
    params = {
        'access_key': AVIATIONSTACK_KEY,
        'arr_iata': AIRPORT_IATA if mode == "arrival" else None,
        'dep_iata': AIRPORT_IATA if mode == "departure" else None
    }
    
    # Clean None values
    params = {k: v for k, v in params.items() if v is not None}

    try:
        response = requests.get('http://api.aviationstack.com/v1/flights', params=params)
        
        # Handle API Errors specifically
        if response.status_code in [401, 403, 404, 429, 500]:
            logger.error(f"API Error {response.status_code}: {response.text}")
            return "API_ERROR"
            
        data = response.json()
        
        if "error" in data:
            logger.error(f"API Logic Error: {data['error']}")
            return "API_ERROR"

        flights = data.get('data', [])
        processed_flights = process_flight_data(flights, mode)
        
        # Update Cache
        data_cache[cache_key] = {"data": processed_flights, "timestamp": now}
        return processed_flights

    except Exception as e:
        logger.error(f"Connection/Parsing Error: {e}")
        return "API_ERROR"

def process_flight_data(flights_raw, mode):
    """
    Filters and processes raw flight data using Pandas logic where applicable.
    """
    processed = []
    now = get_current_pacific_time()

    for f in flights_raw:
        # 1. Passenger Filter: Skip Cargo
        # Note: AviationStack structure varies by plan, checking standard field locations
        is_cargo = f.get('flight', {}).get('is_cargo', False)
        # Sometimes it comes as string "true"/"false"
        if str(is_cargo).lower() == 'true':
            continue

        # 2. Time Extraction & Conversion
        # Use 'estimated' if available, else 'scheduled'
        time_key = 'estimated' if f.get(mode, {}).get('estimated') else 'scheduled'
        time_str = f.get(mode, {}).get(time_key)
        
        if not time_str:
            continue

        # API usually returns UTC or local. AviationStack usually ISO 8601.
        # We parse and convert to Pacific.
        try:
            # Assuming API returns string with offset or UTC. 
            # If no offset, AviationStack often returns local time of airport.
            # Best practice: parse as agnostic then localize if needed, or parse ISO.
            # For robustness, we assume the string needs parsing:
            dt_obj = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            
            # If offset naive, localize to UTC then convert, or if local, localize to Pacific
            if dt_obj.tzinfo is None:
                # Fallback logic: AviationStack 'scheduled' is usually local to airport
                dt_obj = TZ_PACIFIC.localize(dt_obj)
            else:
                dt_obj = dt_obj.astimezone(TZ_PACIFIC)
        except ValueError:
            continue

        # 3. Filter Past Flights
        if dt_obj <= now:
            continue

        # 4. Extract Details
        airline = f.get('airline', {}).get('name', 'Unknown')
        flight_num = f.get('flight', {}).get('iata', 'N/A')
        gate = f.get(mode, {}).get('gate', 'TBD')
        terminal = f.get(mode, {}).get('terminal', '-')

        # 5. Zone Targeting Logic
        zone_info = "Waiting for Gate"
        if gate and gate != "TBD":
            g_str = str(gate).upper()
            if g_str.startswith('C'):
                zone_info = "Zone C (North)"
            elif g_str.startswith('A') or g_str.startswith('B'):
                zone_info = "Zone A/B (South)"
            else:
                zone_info = f"Gate {g_str}"

        # 6. Curbside Timer (Arrivals only)
        ready_time_str = ""
        if mode == "arrival":
            ready_dt = dt_obj + timedelta(minutes=20)
            ready_time_str = ready_dt.strftime("%H:%M")

        processed.append({
            "time_obj": dt_obj,
            "time_str": dt_obj.strftime("%H:%M"),
            "airline": airline,
            "flight": flight_num,
            "gate": gate,
            "zone": zone_info,
            "ready_str": ready_time_str
        })

    # Sort by time
    processed.sort(key=lambda x: x['time_obj'])
    return processed

def detect_surge_clusters(flights_list):
    """
    Identifies if 3+ unique flights land within any 20-minute rolling window.
    Returns a set of flight numbers that are part of a surge.
    """
    if len(flights_list) < 3:
        return set()

    surge_flights = set()
    
    # We use a sliding window approach on the sorted list
    # Convert list to dataframe for easier rolling window calc or just iterate
    # Iteration is cheaper for small lists
    
    for i in range(len(flights_list)):
        current_time = flights_list[i]['time_obj']
        # Look ahead
        count = 1
        window_flights = [flights_list[i]['flight']]
        
        for j in range(i + 1, len(flights_list)):
            delta = (flights_list[j]['time_obj'] - current_time).total_seconds() / 60
            if delta <= 20:
                count += 1
                window_flights.append(flights_list[j]['flight'])
            else:
                break
        
        if count >= 3:
            for f_num in window_flights:
                surge_flights.add(f_num)

    return surge_flights

def analyze_demand(flights_list):
    """
    Calculates demand stats for /status.
    """
    if not flights_list:
        return 0, []

    df = pd.DataFrame(flights_list)
    
    # 1. Next 3 Hours Count
    now = get_current_pacific_time()
    limit = now + timedelta(hours=3)
    
    # Ensure time_obj is datetime64 for pandas operations if needed, 
    # but list comprehension is faster for simple filtering
    next_3h_count = sum(1 for f in flights_list if f['time_obj'] <= limit)

    # 2. Top 3 Busiest Hours (Full schedule)
    # Extract hour from each flight
    hours = [f['time_obj'].strftime("%I %p") for f in flights_list]
    if not hours:
        return next_3h_count, []
        
    hour_counts = pd.Series(hours).value_counts().head(3)
    top_hours = [f"{hour} ({count} flights)" for hour, count in hour_counts.items()]

    return next_3h_count, top_hours

# -----------------------------------------------------------------------------
# BOT COMMAND HANDLERS
# -----------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚖 **GEG Rideshare Assistant**\n\n"
        "Commands:\n"
        "/arrivals - Next incoming flights + Zones\n"
        "/departures - Next outgoing flights\n"
        "/status - Demand strategy & busy hours\n"
        "/weather - Current GEG weather\n"
        "/refresh - Force refresh data",
        parse_mode='Markdown'
    )

async def arrivals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    flights = fetch_flights("arrival")
    
    if flights == "API_ERROR":
        await update.message.reply_text("❌ API Connection Error")
        return

    if not flights:
        await update.message.reply_text("No incoming flights found in the near future.")
        return

    # Surge Detection
    surge_set = detect_surge_clusters(flights)

    msg = ["🛬 **GEG Arrivals (Next 4 Hours)**\n"]
    
    # Limit display to keep message short (e.g., next 10-15 flights)
    display_limit = 15
    
    for f in flights[:display_limit]:
        surge_marker = "⚠️ SURGE CLUSTER ⚠️\n" if f['flight'] in surge_set else ""
        
        line = (
            f"{surge_marker}"
            f"✈️ *{f['flight']}* ({f['airline']})\n"
            f"📍 {f['zone']} (Gate {f['gate']})\n"
            f"⏰ Land: `{f['time_str']}` → 🚕 Ready: `{f['ready_str']}`\n"
            "-----------------------------"
        )
        msg.append(line)

    if len(flights) > display_limit:
        msg.append(f"_+ {len(flights) - display_limit} more flights..._")

    await update.message.reply_text("\n".join(msg), parse_mode='Markdown')

async def departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    flights = fetch_flights("departure")
    
    if flights == "API_ERROR":
        await update.message.reply_text("❌ API Connection Error")
        return

    if not flights:
        await update.message.reply_text("No departing flights found.")
        return

    msg = ["🛫 **GEG Departures**\n"]
    
    for f in flights[:10]:
        line = (
            f"✈️ *{f['flight']}* ({f['airline']})\n"
            f"⏰ Departs: `{f['time_str']}`\n"
            f"📍 Gate: {f['gate']}\n"
        )
        msg.append(line)

    await update.message.reply_text("\n".join(msg), parse_mode='Markdown')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Demand Strategy: Professional and emoji-free.
    """
    flights = fetch_flights("arrival")
    
    if flights == "API_ERROR":
        await update.message.reply_text("API Connection Error")
        return

    next_3h, top_hours = analyze_demand(flights)

    top_hours_str = "\n".join([f"- {h}" for h in top_hours]) if top_hours else "Insufficient data"

    response = (
        "DEMAND STRATEGY REPORT\n"
        "======================\n"
        f"Incoming Volume (Next 3 Hours): {next_3h} flights\n\n"
        "BUSIEST INTERVALS (Next 24h):\n"
        f"{top_hours_str}\n\n"
        "RECOMMENDATION:\n"
        "Position near cell phone lot if volume > 5/hr. "
        "Monitor Zone C for North gates."
    )
    
    await update.message.reply_text(response)

async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    w = fetch_weather()
    if not w:
        await update.message.reply_text("❌ API Connection Error")
        return
        
    await update.message.reply_text(
        f"🌤 **Current GEG Weather**\n"
        f"Temp: {w['temp']}°F\n"
        f"Condition: {w['desc']}\n"
        f"Wind: {w['wind']} mph",
        parse_mode='Markdown'
    )

async def refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Clear cache
    data_cache["arrivals"] = {"data": None, "timestamp": None}
    data_cache["departures"] = {"data": None, "timestamp": None}
    data_cache["weather"] = {"data": None, "timestamp": None}
    
    # Trigger fetch to warm cache
    fetch_flights("arrival")
    
    await update.message.reply_text("🔄 Cache cleared. Data refreshed.")

# -----------------------------------------------------------------------------
# MAIN EXECUTION
# -----------------------------------------------------------------------------

if __name__ == '__main__':
    # Verify Tokens
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN is missing.")
        exit(1)
        
    # Start Flask Keep-Alive in background
    start_keep_alive()

    # Init Bot
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Register Handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('arrivals', arrivals))
    application.add_handler(CommandHandler('departures', departures))
    application.add_handler(CommandHandler('status', status))
    application.add_handler(CommandHandler('weather', weather))
    application.add_handler(CommandHandler('refresh', refresh))

    # Run Bot
    print("Bot is polling...")
    application.run_polling()
