import logging
import os
import time
import requests
import threading
from flask import Flask 
from datetime import datetime, timedelta
import pytz
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from telegram.error import BadRequest

# --- WEB SERVER (KEEPS BOT ALIVE ON RENDER) --- #
app = Flask(__name__)

@app.route('/')
def health_check():
    return "GEG Bot is Alive!"

def run_web_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- CONFIGURATION --- #
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AVIATION_API_KEY = os.getenv("AVIATION_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

AIRPORT_IATA = 'GEG'
TIMEZONE = pytz.timezone('America/Los_Angeles')

# --- KNOWLEDGE BASE --- #
BANNED_CARRIERS = [
    'FEDEX', 'UPS', 'AMAZON AIR', 'AMERIFLIGHT', 'EMPIRE', 'KALITTA', 
    'WESTERN AIR EXPRESS', 'AIRPAC', 'CORPORATE AIR', 'PRIVATE', 'UNKNOWN'
]

TERMINAL_MAP = {
    'Southwest Airlines': 'Zone A/B (Rotunda)',
    'Delta Air Lines': 'Zone A/B (Rotunda)',
    'United Airlines': 'Zone A/B (Rotunda)',
    'Sun Country Airlines': 'Zone A/B (Rotunda)',
    'Allegiant Air': 'Zone A/B (Rotunda)',
    'Alaska Airlines': 'Zone C (North)',
    'American Airlines': 'Zone C (North)',
    'Frontier Airlines': 'Zone C (North)',
}

# --- GLOBAL CACHE --- #
# Simplified keys to prevent KeyErrors
flight_cache = {
    "arrival": {"data": None, "timestamp": 0},
    "departure": {"data": None, "timestamp": 0}
}
CACHE_DURATION = 1800  # 30 Minutes

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
        if r.get('cod') != 200:
            return None, "Weather Unavailable"
        temp = round(r['main']['temp'])
        desc = r['weather'][0]['description'].title()
        return temp, desc
    except Exception as e:
        logger.error(f"Weather Error: {e}")
        return None, "Unavailable"

def fetch_flights(mode):
    """
    Mode must be 'arrival' or 'departure'
    """
    global flight_cache
    current_time = time.time()
    
    # 1. Check Cache
    if flight_cache[mode]["data"] is not None and (current_time - flight_cache[mode]["timestamp"] < CACHE_DURATION):
        logger.info(f"Using cached {mode} data.")
        raw_data = flight_cache[mode]["data"]
    else:
        # 2. Fetch New Data
        logger.info(f"Fetching {mode} from API...")
        url = "http://api.aviationstack.com/v1/flights"
        params = {
            'access_key': AVIATION_API_KEY,
            'arr_iata' if mode == 'arrival' else 'dep_iata': AIRPORT_IATA,
            'limit': 100 
        }
        try:
            r = requests.get(url, params=params, timeout=20)
            data = r.json()
            
            if 'error' in data:
                logger.error(f"API Error: {data['error']}")
                return []
                
            raw_data = data.get('data', [])
            flight_cache[mode]["data"] = raw_data
            flight_cache[mode]["timestamp"] = current_time
        except Exception as e:
            logger.error(f"Network Error: {e}")
            return []

    # 3. Process Data
    now = get_spokane_time()
    processed_flights = []

    for f in raw_data:
        try:
            # Airline Check
            airline_obj = f.get('airline')
            if not airline_obj: continue 
            airline_name = airline_obj.get('name', 'UNKNOWN')
            
            if any(banned in airline_name.upper() for banned in BANNED_CARRIERS): continue
            if airline_name not in TERMINAL_MAP: continue

            # Time Check
            time_key = 'arrival' if mode == 'arrival' else 'departure'
            time_obj = f.get(time_key)
            if not time_obj: continue
            
            time_str = time_obj.get('estimated') or time_obj.get('scheduled')
            if not time_str: continue

            flight_time_utc = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            flight_time_local = flight_time_utc.astimezone(TIMEZONE)

            # Filter Past Flights (keep flights from 20 mins ago onwards)
            if flight_time_local < now - timedelta(minutes=20): continue
                
            zone = TERMINAL_MAP.get(airline_name, "Zone A/B")
            # For departures, pickup time isn't relevant, but we calculate it for consistency
            pickup_time = flight_time_local + timedelta(minutes=20)
            
            flight_num = f.get('flight', {}).get('iata', 'N/A')

            processed_flights.append({
                'airline': airline_name,
                'flight_no': flight_num,
                'time': flight_time_local,
                'time_str': flight_time_local.strftime('%H:%M'),
                'pickup_str': pickup_time.strftime('%H:%M'),
                'zone': zone
            })
        except Exception:
            continue

    processed_flights.sort(key=lambda x: x['time'])
    return processed_flights

async def safe_edit_message(context, chat_id, message_id, text):
    """Prevents crash if message hasn't changed"""
    try:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            await context.bot.send_message(chat_id=chat_id, text=f"Error: {e}")

# --- BOT COMMANDS --- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚖 **GEG Driver Assistant Online**\nUse /status, /arrivals, or /departures")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔄 Analyzing grid...")
    try:
        temp, weather_desc = get_weather()
        # Use arrival count for general demand
        arrivals = fetch_flights('arrival')
        
        count = len([f for f in arrivals if f['time'] < get_spokane_time() + timedelta(hours=1)])
        
        strategy = "⚪ Stay Downtown"
        if count >= 2: strategy = "🟡 Moderate Demand"
        if count >= 4: strategy = "🟢 HIGH DEMAND"
        
        if weather_desc and ("Rain" in weather_desc or "Snow" in weather_desc):
            strategy += " (☔ Surge Likely)"
        
        text = (f"📊 **STATUS: {get_spokane_time().strftime('%I:%M %p')}**\n"
                f"🌡️ {temp}°F, {weather_desc}\n"
                f"✈️ Inbound (1h): {count} flights\n"
                f"🚦 {strategy}")
        
        await safe_edit_message(context, update.effective_chat.id, msg.message_id, text)
    except Exception as e:
        await safe_edit_message(context, update.effective_chat.id, msg.message_id, f"Error: {e}")

async def show_arrivals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔄 Fetching arrivals...")
    try:
        flights = fetch_flights('arrival')
        if not flights:
            await safe_edit_message(context, update.effective_chat.id, msg.message_id, "💤 No upcoming passenger arrivals.")
            return

        text = "🛬 **ARRIVALS (GEG)**\n"
        for f in flights[:15]: 
            text += f"\n🕒 {f['time_str']} | {f['airline']} | {f['flight_no']}\n📍 {f['zone']} | 🚕 Pickup: {f['pickup_str']}\n"
            
        await safe_edit_message(context, update.effective_chat.id, msg.message_id, text)
    except Exception as e:
        await safe_edit_message(context, update.effective_chat.id, msg.message_id, f"Error: {e}")

async def show_departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔄 Fetching departures...")
    try:
        # FETCH DEPARTURES (TEXT MODE)
        flights = fetch_flights('departure')
        
        if not flights:
            await safe_edit_message(context, update.effective_chat.id, msg.message_id, "💤 No upcoming passenger departures.")
            return

        text = "🛫 **DEPARTURES (GEG)**\n"
        for f in flights[:15]: 
            # Format: Time | Airline | Flight
            # Zone info is useful for drivers dropping off
            text += f"\n🕒 {f['time_str']} | {f['airline']} | {f['flight_no']}\n📍 {f['zone']} (Drop-off)\n"
            
        await safe_edit_message(context, update.effective_chat.id, msg.message_id, text)
    except Exception as e:
        await safe_edit_message(context, update.effective_chat.id, msg.message_id, f"Error: {e}")

if __name__ == '__main__':
    # Start Keep-Alive Server
    threading.Thread(target=run_web_server).start()
    
    if not all([TELEGRAM_TOKEN, AVIATION_API_KEY, WEATHER_API_KEY]):
        print("CRITICAL: Missing API Keys!")
    
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('status', status))
    application.add_handler(CommandHandler('arrivals', show_arrivals))
    application.add_handler(CommandHandler('departures', show_departures))
    
    print("Bot is running...")
    application.run_polling()
