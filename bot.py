import logging
import os
import requests
import threading
import time  # <--- THIS WAS MISSING
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
    return "GEG AirLabs Pro Bot is Online!"

def run_web_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- CONFIGURATION --- #
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AIRLABS_API_KEY = os.getenv("AIRLABS_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

AIRPORT_IATA = 'GEG'
TIMEZONE = pytz.timezone('America/Los_Angeles')

# --- INTELLIGENT ZONING SYSTEM --- #
TERMINAL_MAP = {
    'DL': 'Zone A/B (Rotunda)', # Delta
    'UA': 'Zone A/B (Rotunda)', # United
    'WN': 'Zone A/B (Rotunda)', # Southwest
    'SY': 'Zone A/B (Rotunda)', # Sun Country
    'G4': 'Zone A/B (Rotunda)', # Allegiant
    'AS': 'Zone C (North)',     # Alaska
    'QX': 'Zone C (North)',     # Horizon (Alaska)
    'AA': 'Zone C (North)',     # American
    'F9': 'Zone C (North)'      # Frontier
}

# --- GLOBAL CACHE --- #
flight_cache = {
    "arrival": {"data": None, "timestamp": 0},
    "departure": {"data": None, "timestamp": 0}
}
CACHE_DURATION = 900  # 15 Minutes

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
    global flight_cache
    current_time = time.time()  # This line crashed before because 'time' wasn't imported
    
    # 1. Check Cache
    if flight_cache[mode]["data"] and (current_time - flight_cache[mode]["timestamp"] < CACHE_DURATION):
        logger.info(f"Using cached {mode} data.")
        return flight_cache[mode]["data"]

    logger.info(f"Fetching {mode} from AirLabs Schedules...")
    
    base_url = "https://airlabs.co/api/v9/schedules"
    
    params = {
        'api_key': AIRLABS_API_KEY,
        'arr_iata' if mode == 'arrival' else 'dep_iata': AIRPORT_IATA,
        'limit': 50 
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
        
        seen_flights = set()

        for f in raw_flights:
            try:
                airline_code = f.get('airline_iata')
                flight_num = f.get('flight_number')
                
                if not airline_code or not flight_num: continue

                # Filter Codeshares
                unique_id = f"{airline_code}{flight_num}"
                if unique_id in seen_flights: continue
                seen_flights.add(unique_id)

                # Filter Cargo
                if airline_code in ['FX', '5X', 'PO', 'K4', 'QY']: continue 

                # Time Logic
                if mode == 'arrival':
                    time_str = f.get('arr_estimated') or f.get('arr_time')
                else:
                    time_str = f.get('dep_estimated') or f.get('dep_time')
                
                if not time_str: continue

                # Parse Time
                flight_dt_naive = datetime.strptime(time_str, '%Y-%m-%d %H:%M')
                flight_local = TIMEZONE.localize(flight_dt_naive)

                # Filter Window (-20 mins to +24 hours)
                if flight_local < now - timedelta(minutes=20): continue
                if flight_local > now + timedelta(hours=24): continue

                # Zone Logic
                api_terminal = f.get('arr_terminal') if mode == 'arrival' else f.get('dep_terminal')
                
                zone = "Check Screen"
                if api_terminal:
                    if 'C' in str(api_terminal): zone = "Zone C (North)"
                    elif 'A' in str(api_terminal) or 'B' in str(api_terminal): zone = "Zone A/B (Rotunda)"
                else:
                    zone = TERMINAL_MAP.get(airline_code, "Zone A/B (Default)")

                status = f.get('status', '').lower()
                if status == 'cancelled': continue 

                processed_flights.append({
                    'code': airline_code,
                    'num': flight_num,
                    'time': flight_local,
                    'time_str': flight_local.strftime('%H:%M'),
                    'zone': zone,
                    'status': status
                })
            except Exception as e:
                logger.error(f"Parse Error: {e}")
                continue

        processed_flights.sort(key=lambda x: x['time'])
        
        flight_cache[mode]["data"] = processed_flights
        flight_cache[mode]["timestamp"] = current_time
        return processed_flights

    except Exception as e:
        logger.error(f"API Failure: {e}")
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
    await update.message.reply_text(
        "🚘 **GEG Pro Driver Bot (AirLabs Edition)**\n"
        "Data Source: AirLabs Schedules [Real-Time + Future]\n\n"
        "/status - Demand Strategy\n"
        "/arrivals - Incoming Passenger Flights\n"
        "/departures - Outgoing Passenger Flights"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("📡 Analyzing AirLabs Schedule...")
    try:
        temp, weather = get_weather()
        flights = fetch_flights('arrival')
        
        now = get_spokane_time()
        count = len([f for f in flights if now < f['time'] < now + timedelta(hours=1)])
        
        strategy = "⚪ **Stay Downtown**"
        if count >= 2: strategy = "🟡 **Head to Cell Phone Lot**"
        if count >= 4: strategy = "🟢 **GO TO AIRPORT NOW**"
        
        if weather and ("Rain" in weather or "Snow" in weather):
            strategy += " (☔ Surge Likely)"
        
        text = (f"📊 **LIVE STATUS: {now.strftime('%I:%M %p')}**\n"
                f"🌡️ {temp}°F, {weather}\n"
                f"🛬 **Inbound (1hr):** {count} planes\n"
                f"🚦 **Strategy:** {strategy}")
        
        await safe_edit(context, update.effective_chat.id, msg.message_id, text)
    except Exception as e:
        await safe_edit(context, update.effective_chat.id, msg.message_id, f"Error: {e}")

async def show_arrivals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("📡 Fetching Arrivals...")
    flights = fetch_flights('arrival')
    
    if not flights:
        await safe_edit(context, update.effective_chat.id, msg.message_id, "💤 No upcoming arrivals found in schedule.")
        return

    text = "🛬 **INBOUND SCHEDULE (GEG)**\n"
    for f in flights[:15]:
        pickup = (f['time'] + timedelta(minutes=20)).strftime('%H:%M')
        text += f"`{f['time_str']}` {f['code']}{f['num']}\n📍 {f['zone']} | 🚕 *{pickup}*\n\n"
    
    await safe_edit(context, update.effective_chat.id, msg.message_id, text)

async def show_departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("📡 Fetching Departures...")
    flights = fetch_flights('departure')
    
    if not flights:
        await safe_edit(context, update.effective_chat.id, msg.message_id, "💤 No upcoming departures found in schedule.")
        return

    text = "🛫 **OUTBOUND SCHEDULE (GEG)**\n"
    for f in flights[:15]:
        text += f"`{f['time_str']}` {f['code']}{f['num']}\n📍 {f['zone']}\n\n"
    
    await safe_edit(context, update.effective_chat.id, msg.message_id, text)

if __name__ == '__main__':
    threading.Thread(target=run_web_server).start()
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('status', status))
    application.add_handler(CommandHandler('arrivals', show_arrivals))
    application.add_handler(CommandHandler('departures', show_departures))
    application.run_polling()
