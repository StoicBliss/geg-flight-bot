import logging
import os
import requests
import threading
from flask import Flask 
from datetime import datetime, timedelta
import pytz
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from telegram.error import BadRequest

# --- WEB SERVER (KEEPS BOT ALIVE) --- #
app = Flask(__name__)

@app.route('/')
def health_check():
    return "GEG AirLabs Bot is Alive!"

def run_web_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- CONFIGURATION --- #
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AIRLABS_API_KEY = os.getenv("AIRLABS_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

AIRPORT_IATA = 'GEG'
TIMEZONE = pytz.timezone('America/Los_Angeles')

# --- TERMINAL MAP (Relaxed Match) --- #
# AirLabs usually provides terminal data, but we keep this as a fallback.
TERMINAL_MAP = {
    'Southwest': 'Zone A/B (Rotunda)',
    'Delta': 'Zone A/B (Rotunda)',
    'United': 'Zone A/B (Rotunda)',
    'Alaska': 'Zone C (North)',
    'American': 'Zone C (North)',
    'Allegiant': 'Zone A/B (Rotunda)',
    'Frontier': 'Zone C (North)',
    'Horizon': 'Zone C (North)',
    'SkyWest': 'Check Screens' 
}

# --- GLOBAL CACHE --- #
flight_cache = {
    "arrival": {"data": None, "timestamp": 0},
    "departure": {"data": None, "timestamp": 0}
}
CACHE_DURATION = 900  # 15 Minutes Cache (Saves API credits)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- HELPER FUNCTIONS --- #
def get_spokane_time():
    return datetime.now(TIMEZONE)

def get_weather():
    url = f"http://api.openweathermap.org/data/2.5/weather?lat=47.619&lon=-117.535&appid={WEATHER_API_KEY}&units=imperial"
    try:
        r = requests.get(url, timeout=5).json()
        if r.get('cod') != 200: return None, "Unavailable"
        temp = round(r['main']['temp'])
        desc = r['weather'][0]['description'].title()
        return temp, desc
    except:
        return None, "Unavailable"

def fetch_flights(mode):
    """
    Fetches flights from AirLabs /schedules endpoint.
    This ensures we get FUTURE flights for planning.
    """
    global flight_cache
    current_time = time.time()
    
    if flight_cache[mode]["data"] and (current_time - flight_cache[mode]["timestamp"] < CACHE_DURATION):
        logger.info(f"Using cached {mode} data.")
        return flight_cache[mode]["data"]

    logger.info(f"Fetching {mode} from AirLabs...")
    
    # Endpoint: https://airlabs.co/api/v9/schedules
    base_url = "https://airlabs.co/api/v9/schedules"
    
    params = {
        'api_key': AIRLABS_API_KEY,
        # If mode is arrival, we want flights arriving AT GEG (arr_iata=GEG)
        # If mode is departure, we want flights departing FROM GEG (dep_iata=GEG)
        'arr_iata' if mode == 'arrival' else 'dep_iata': AIRPORT_IATA,
        'limit': 50  # Free tier max limit per request
    }

    try:
        r = requests.get(base_url, params=params, timeout=15)
        data = r.json()
        
        if 'error' in data:
            logger.error(f"AirLabs Error: {data['error']}")
            return []

        raw_flights = data.get('response', [])
        processed_flights = []
        now = get_spokane_time()

        for f in raw_flights:
            # airline_iata is typically the code (e.g. AA, DL)
            # We might not get the full name, so we use the IATA code or name if available
            airline_name = f.get('airline_iata') or f.get('airline_icao') or "Unknown"
            flight_num = f.get('flight_number') or f.get('flight_iata') or "N/A"
            
            # Skip cargo if possible (AirLabs doesn't always flag it explicitly in free tier, 
            # but we filter by known passenger terminals later)
            
            # Get Timing
            # AirLabs gives 'dep_time' (scheduled) and 'dep_estimated' (live)
            if mode == 'arrival':
                time_str = f.get('arr_estimated') or f.get('arr_time')
            else:
                time_str = f.get('dep_estimated') or f.get('dep_time')
            
            if not time_str: continue

            # Parse Time (Format: "2023-12-07 14:30")
            try:
                # AirLabs times are usually local to the airport
                # But sometimes they come as UTC. The safe bet is to assume airport local time 
                # because the documentation says "Airport Time Zone"
                flight_local = datetime.strptime(time_str, '%Y-%m-%d %H:%M')
                # We interpret this 'naive' time as Spokane time
                flight_local = TIMEZONE.localize(flight_local)
            except ValueError:
                continue

            # Filter: Only show flights from NOW onwards (up to 24h)
            # We allow a small buffer (e.g. landed 20 mins ago)
            if flight_local < now - timedelta(minutes=20): continue
            if flight_local > now + timedelta(hours=24): continue

            # Determine Zone
            # AirLabs provides 'dep_terminal' / 'arr_terminal'
            terminal = f.get('arr_terminal') if mode == 'arrival' else f.get('dep_terminal')
            
            if terminal:
                zone = f"Concourse {terminal}"
                # Map Concourse A/B/C to your Zones if straightforward
                if terminal in ['A', 'B']: zone = "Zone A/B (Rotunda)"
                elif terminal == 'C': zone = "Zone C (North)"
            else:
                # Fallback to fuzzy match on Airline Code
                zone = "Zone A/B" # Default
                # Simple map based on IATA codes
                if 'AS' in airline_name: zone = "Zone C (North)" # Alaska
                elif 'AA' in airline_name: zone = "Zone C (North)" # American
                elif 'DL' in airline_name: zone = "Zone A/B (Rotunda)" # Delta
                elif 'UA' in airline_name: zone = "Zone A/B (Rotunda)" # United
                elif 'WN' in airline_name: zone = "Zone A/B (Rotunda)" # Southwest

            processed_flights.append({
                'airline': airline_name, # Shows code like 'AA' or 'DL'
                'flight_no': flight_num,
                'time': flight_local,
                'time_str': flight_local.strftime('%H:%M'),
                'zone': zone
            })

        # Sort by time
        processed_flights.sort(key=lambda x: x['time'])
        
        # Cache results
        flight_cache[mode]["data"] = processed_flights
        flight_cache[mode]["timestamp"] = current_time
        return processed_flights

    except Exception as e:
        logger.error(f"API Error: {e}")
        return []

async def safe_edit(context, chat_id, msg_id, text):
    try:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text, parse_mode='Markdown')
    except BadRequest:
        pass 
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text=text)

# --- BOT COMMANDS --- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚁 **GEG AirLabs Driver Bot**\nPowered by AirLabs Schedules.\n\n/status - Strategy\n/arrivals - Arrivals Board\n/departures - Departures Board")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("📡 Checking Schedule...")
    try:
        temp, weather = get_weather()
        flights = fetch_flights('arrival')
        
        # Count flights landing in next 60 mins
        now = get_spokane_time()
        count = len([f for f in flights if now < f['time'] < now + timedelta(hours=1)])
        
        strategy = "⚪ **Stay Downtown**"
        if count >= 2: strategy = "🟡 **Head to Cell Phone Lot**"
        if count >= 4: strategy = "🟢 **GO TO AIRPORT NOW**"
        
        text = (f"📊 **LIVE STATUS: {now.strftime('%I:%M %p')}**\n"
                f"🌡️ {temp}°F, {weather}\n"
                f"🛬 **Inbound (1hr):** {count} planes\n"
                f"🚦 **Strategy:** {strategy}")
        
        await safe_edit(context, update.effective_chat.id, msg.message_id, text)
    except Exception as e:
        await safe_edit(context, update.effective_chat.id, msg.message_id, f"Error: {e}")

async def show_arrivals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("📡 Fetching Arrivals Schedule...")
    flights = fetch_flights('arrival')
    if not flights:
        await safe_edit(context, update.effective_chat.id, msg.message_id, "No upcoming arrivals found in schedule.")
        return

    text = "🛬 **INBOUND SCHEDULE (GEG)**\n"
    for f in flights[:15]:
        pickup = (f['time'] + timedelta(minutes=20)).strftime('%H:%M')
        # Display: Time | Code | Flight
        text += f"`{f['time_str']}` {f['airline']} {f['flight_no']}\n📍 {f['zone']} | 🚕 *{pickup}*\n\n"
    
    await safe_edit(context, update.effective_chat.id, msg.message_id, text)

async def show_departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("📡 Fetching Departures Schedule...")
    flights = fetch_flights('departure')
    if not flights:
        await safe_edit(context, update.effective_chat.id, msg.message_id, "No upcoming departures found in schedule.")
        return

    text = "🛫 **OUTBOUND SCHEDULE (GEG)**\n"
    for f in flights[:15]:
        text += f"`{f['time_str']}` {f['airline']} {f['flight_no']}\n📍 {f['zone']}\n\n"
    
    await safe_edit(context, update.effective_chat.id, msg.message_id, text)

if __name__ == '__main__':
    threading.Thread(target=run_web_server).start()
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('status', status))
    application.add_handler(CommandHandler('arrivals', show_arrivals))
    application.add_handler(CommandHandler('departures', show_departures))
    application.run_polling()
