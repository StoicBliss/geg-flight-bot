import logging
import os
import time
import requests
import pandas as pd
import matplotlib.pyplot as plt
import io
from datetime import datetime, timedelta
import pytz
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler

# --- CONFIGURATION --- #
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
AVIATION_API_KEY = "YOUR_AVIATIONSTACK_KEY"
WEATHER_API_KEY = "YOUR_OPENWEATHERMAP_KEY"

# Spokane Configuration
AIRPORT_IATA = 'GEG'
TIMEZONE = pytz.timezone('America/Los_Angeles')

# --- KNOWLEDGE BASE --- #
# Cargo/Private carriers to EXCLUDE
BANNED_CARRIERS = [
    'FEDEX', 'UPS', 'EMPIRE', 'AMERIFLIGHT', 'KALITTA', 'WESTERN AIR EXPRESS',
    'ALPINE AIR', 'CORPORATE AIR', 'PRIVATE', 'UNKNOWN'
]

# Airline to Terminal Mapping (Spokane Specific)
# Concourse A/B = Zone A/B (Southwest, Delta, United)
# Concourse C = Zone C (Alaska, American, Frontier)
TERMINAL_MAP = {
    'Southwest Airlines': 'Zone A/B (Rotunda)',
    'Delta Air Lines': 'Zone A/B (Rotunda)',
    'United Airlines': 'Zone A/B (Rotunda)',
    'Sun Country Airlines': 'Zone A/B (Rotunda)',
    'Alaska Airlines': 'Zone C (North)',
    'American Airlines': 'Zone C (North)',
    'Frontier Airlines': 'Zone C (North)',
    'Allegiant Air': 'Zone A/B (Rotunda)'
}

# --- GLOBAL CACHE --- #
flight_cache = {
    "arrivals": {"data": None, "timestamp": 0},
    "departures": {"data": None, "timestamp": 0}
}
CACHE_DURATION = 1800  # 30 minutes in seconds

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- HELPER FUNCTIONS --- #

def get_spokane_time():
    return datetime.now(TIMEZONE)

def get_weather():
    """Fetches current weather for Spokane Airport."""
    url = f"http://api.openweathermap.org/data/2.5/weather?lat=47.619&lon=-117.535&appid={WEATHER_API_KEY}&units=imperial"
    try:
        r = requests.get(url).json()
        temp = round(r['main']['temp'])
        desc = r['weather'][0]['description'].title()
        return temp, desc
    except Exception as e:
        return None, "Unavailable"

def fetch_flights(mode='arrival'):
    """
    Fetches flights from Aviationstack with 30-min caching.
    Refilters by time on every call.
    """
    global flight_cache
    current_time = time.time()
    
    # 1. Check Cache
    if flight_cache[mode]["data"] is not None and (current_time - flight_cache[mode]["timestamp"] < CACHE_DURATION):
        logging.info(f"Using cached {mode} data.")
        raw_data = flight_cache[mode]["data"]
    else:
        # 2. Fetch New Data
        logging.info(f"Fetching new {mode} data from API.")
        url = "http://api.aviationstack.com/v1/flights"
        params = {
            'access_key': AVIATION_API_KEY,
            'arr_iata' if mode == 'arrival' else 'dep_iata': AIRPORT_IATA,
            'limit': 100 
        }
        try:
            r = requests.get(url, params=params)
            data = r.json()
            if 'data' not in data:
                return []
            raw_data = data['data']
            # Update Cache
            flight_cache[mode]["data"] = raw_data
            flight_cache[mode]["timestamp"] = current_time
        except Exception as e:
            logging.error(f"API Error: {e}")
            return []

    # 3. Process & Filter Data (Run every time)
    now = get_spokane_time()
    processed_flights = []

    for f in raw_data:
        # Basic Validation
        if not f['airline']: continue
        airline_name = f['airline']['name']
        
        # FILTER: Exclude Cargo/Private
        if any(banned in airline_name.upper() for banned in BANNED_CARRIERS):
            continue

        # Get Timing
        if mode == 'arrival':
            # Use estimated arrival if available, else scheduled
            time_str = f['arrival']['estimated'] or f['arrival']['scheduled']
        else:
            time_str = f['departure']['estimated'] or f['departure']['scheduled']
            
        if not time_str: continue

        # Parse Time (API returns UTC usually, need to ensure awareness)
        # Aviationstack dates are ISO 8601. 
        flight_time_utc = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        flight_time_local = flight_time_utc.astimezone(TIMEZONE)

        # FILTER: Strict Future/Current Check
        # If flight is older than now (already landed/departed), skip it
        if flight_time_local < now:
            continue
            
        # Determine Zone
        zone = TERMINAL_MAP.get(airline_name, "Zone A/B (Default)")

        # Calculate "True Pickup" (Arrival + 20 mins)
        pickup_time = flight_time_local + timedelta(minutes=20)

        processed_flights.append({
            'airline': airline_name,
            'flight_no': f['flight']['iata'],
            'time': flight_time_local,
            'time_str': flight_time_local.strftime('%H:%M'),
            'pickup_str': pickup_time.strftime('%H:%M'),
            'zone': zone
        })

    # Sort by time
    processed_flights.sort(key=lambda x: x['time'])
    return processed_flights

def generate_graph(flights, title):
    """Generates a bar chart for flight volume by hour."""
    if not flights:
        return None

    df = pd.DataFrame(flights)
    df['hour'] = df['time'].apply(lambda x: x.strftime('%I %p')) # 02 PM
    
    # Count flights per hour
    counts = df['hour'].value_counts().sort_index()
    
    # Plotting
    plt.figure(figsize=(10, 5))
    colors = ['#4CAF50' if x < 5 else '#FF5722' for x in counts.values] # Orange if busy
    bars = plt.bar(counts.index, counts.values, color=colors)
    
    plt.title(f"GEG {title} Demand (Next 24h)", fontsize=14, fontweight='bold')
    plt.xlabel("Hour Window", fontsize=12)
    plt.ylabel("Flight Count", fontsize=12)
    plt.xticks(rotation=45)
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    
    # Add numbers on top of bars
    for bar in bars:
        yval = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2, yval + 0.1, int(yval), ha='center', fontweight='bold')

    # Save to buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close()
    return buf

# --- BOT COMMANDS --- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚖 **GEG Driver Assistant Online**\n\n"
        "Commands:\n"
        "/status - Strategy, Weather & Best Shift\n"
        "/arrivals - Incoming flights + Pickup Timer\n"
        "/departures - Outgoing flights + Peak Graph"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔄 Analyzing grid...")
    
    # Get Data
    temp, weather_desc = get_weather()
    arrivals = fetch_flights('arrival')
    
    # Strategy Logic
    next_hour_count = len([f for f in arrivals if f['time'] < get_spokane_time() + timedelta(hours=1)])
    
    strategy = "⚪ Stay Downtown / Rest"
    score = 1
    
    if next_hour_count >= 2:
        strategy = "🟡 Moderate Demand - Head to Airport Queue"
        score = 5
    if next_hour_count >= 4:
        strategy = "🟢 HIGH DEMAND - Go Immediately"
        score = 8
    
    # Weather multiplier
    if "Rain" in weather_desc or "Snow" in weather_desc:
        strategy += " (☔ Surge Likely)"
        score += 2
        
    now_str = get_spokane_time().strftime('%I:%M %p')
    
    text = (
        f"📊 **STATUS REPORT: {now_str}**\n"
        f"---------------------------------\n"
        f"🌡️ **Weather:** {temp}°F, {weather_desc}\n"
        f"✈️ **Inbound (Next 1h):** {next_hour_count} flights\n"
        f"🚦 **Strategy:** {strategy}\n"
        f"📈 **Surge Score:** {score}/10\n"
    )
    
    await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text=text, parse_mode='Markdown')

async def show_arrivals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔄 Fetching live arrival grid...")
    flights = fetch_flights('arrival')
    
    if not flights:
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="💤 No upcoming passenger arrivals found nearby.")
        return

    text = "🛬 **UPCOMING ARRIVALS (GEG)**\nFormat: Landed | Airline | Zone | **True Pickup**\n\n"
    
    for f in flights[:15]: # Show next 15 only to keep it clean
        line = f"🕒 {f['time_str']} | {f['airline']} | {f['flight_no']}\n📍 {f['zone']} | 🚕 **{f['pickup_str']}**\n\n"
        text += line
        
    await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text=text)

async def show_departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Generating demand graph...")
    flights = fetch_flights('departure')
    
    if not flights:
        await update.message.reply_text("💤 No upcoming departures found.")
        return

    # Generate Graph
    graph_img = generate_graph(flights, "Departure")
    
    await update.message.reply_photo(photo=InputFile(graph_img, filename="chart.png"), caption="📊 **Departure Peaks (Drop-off Opportunities)**")

# --- MAIN --- #
if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('status', status))
    application.add_handler(CommandHandler('arrivals', show_arrivals))
    application.add_handler(CommandHandler('departures', show_departures))
    
    print("Bot is running...")
    application.run_polling()
