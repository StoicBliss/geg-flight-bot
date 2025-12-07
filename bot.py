import logging
import os
import time
import requests
import pandas as pd
import matplotlib
matplotlib.use('Agg') # Force no-screen mode for Render
import matplotlib.pyplot as plt
import io
import threading
from flask import Flask 
from datetime import datetime, timedelta
import pytz
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from telegram.error import BadRequest

# --- WEB SERVER (KEEPS BOT ALIVE) --- #
app = Flask(__name__)

@app.route('/')
def health_check():
    return "GEG Bot is Alive!"

def run_web_server():
    # Render assigns a random port to the PORT env var
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
# Defined with BOTH keys to prevent KeyError typos
flight_cache = {
    "arrival": {"data": None, "timestamp": 0},
    "departure": {"data": None, "timestamp": 0},
    "arrivals": {"data": None, "timestamp": 0},    # Fallback
    "departures": {"data": None, "timestamp": 0}   # Fallback
}
CACHE_DURATION = 1800 

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

def fetch_flights(mode='arrival'):
    """
    Safe fetch that handles singular/plural keys and null API data
    """
    global flight_cache
    current_time = time.time()
    
    # Normalize key (handle user typo risk)
    cache_key = mode
    if mode not in flight_cache:
        # If 'arrivals' was passed, map to 'arrival'
        cache_key = 'arrival' if 'arr' in mode else 'departure'

    # 1. Check Cache
    if flight_cache[cache_key]["data"] is not None and (current_time - flight_cache[cache_key]["timestamp"] < CACHE_DURATION):
        logger.info(f"Using cached {cache_key} data.")
        raw_data = flight_cache[cache_key]["data"]
    else:
        # 2. Fetch New Data
        logger.info(f"Fetching {cache_key} from API...")
        url = "http://api.aviationstack.com/v1/flights"
        params = {
            'access_key': AVIATION_API_KEY,
            'arr_iata' if 'arr' in mode else 'dep_iata': AIRPORT_IATA,
            'limit': 100 
        }
        try:
            r = requests.get(url, params=params, timeout=20)
            data = r.json()
            
            if 'error' in data:
                logger.error(f"API Error: {data['error']}")
                return []
                
            raw_data = data.get('data', [])
            flight_cache[cache_key]["data"] = raw_data
            flight_cache[cache_key]["timestamp"] = current_time
        except Exception as e:
            logger.error(f"Network Error: {e}")
            return []

    # 3. Process Data (Safe Mode)
    now = get_spokane_time()
    processed_flights = []

    for f in raw_data:
        try:
            # SAFETY CHECK 1: Handle if 'airline' is None
            airline_obj = f.get('airline')
            if not airline_obj: continue 
            airline_name = airline_obj.get('name', 'UNKNOWN')
            
            # Filter Banned
            if any(banned in airline_name.upper() for banned in BANNED_CARRIERS): continue
            
            # Filter by Terminal Map (Strict)
            if airline_name not in TERMINAL_MAP: continue

            # SAFETY CHECK 2: Handle if 'arrival'/'departure' is None
            time_key = 'arrival' if 'arr' in mode else 'departure'
            time_obj = f.get(time_key)
            if not time_obj: continue
            
            time_str = time_obj.get('estimated') or time_obj.get('scheduled')
            if not time_str: continue

            # SAFETY CHECK 3: Date Parsing
            flight_time_utc = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            flight_time_local = flight_time_utc.astimezone(TIMEZONE)

            # Filter Past Flights (15 min buffer)
            if flight_time_local < now - timedelta(minutes=15): continue
                
            zone = TERMINAL_MAP.get(airline_name, "Zone A/B")
            pickup_time = flight_time_local + timedelta(minutes=20)
            
            # SAFETY CHECK 4: Flight Number
            flight_num = f.get('flight', {}).get('iata', 'N/A')

            processed_flights.append({
                'airline': airline_name,
                'flight_no': flight_num,
                'time': flight_time_local,
                'time_str': flight_time_local.strftime('%H:%M'),
                'pickup_str': pickup_time.strftime('%H:%M'),
                'zone': zone
            })
        except Exception as e:
            # Log bad item but continue loop
            continue

    processed_flights.sort(key=lambda x: x['time'])
    return processed_flights

def generate_graph(flights, title):
    if not flights: return None
    try:
        df = pd.DataFrame(flights)
        now = get_spokane_time()
        # Filter next 24h
        df = df[df['time'] < now + timedelta(hours=24)]
        if df.empty: return None

        df['hour'] = df['time'].apply(lambda x: x.strftime('%I %p')) 
        next_24_hours = [(now + timedelta(hours=i)).strftime('%I %p') for i in range(24)]
        
        # Safe count
        counts = df['hour'].value_counts().reindex(next_24_hours, fill_value=0)
        counts = counts[counts > 0]
        if counts.empty: return None

        plt.figure(figsize=(10, 5))
        colors = ['#4CAF50' if x < 4 else '#FF5722' for x in counts.values] 
        bars = plt.bar(counts.index, counts.values, color=colors)
        plt.title(f"GEG {title} Demand (Next {len(counts)} Hours)", fontsize=14, fontweight='bold')
        plt.xlabel("Hour Window", fontsize=12)
        plt.ylabel("Flight Count", fontsize=12)
        plt.xticks(rotation=45, ha='right')
        plt.grid(axis='y', linestyle='--', alpha=0.7)
        
        for bar in bars:
            yval = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2, yval + 0.1, int(yval), ha='center', fontweight='bold')

        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight')
        buf.seek(0)
        plt.close()
        return buf
    except Exception as e:
        logger.error(f"Graph Gen Error: {e}")
        return None

# --- BOT COMMANDS --- #

async def safe_edit_message(context, chat_id, message_id, text):
    """Prevents 'Message Not Modified' crash"""
    try:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass # Ignore if text is same
        else:
            await context.bot.send_message(chat_id=chat_id, text=f"Error: {e}")
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"System Error: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("GEG Driver Assistant Online. Use /status, /arrivals, or /departures.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("Analyzing grid...")
    try:
        temp, weather_desc = get_weather()
        arrivals = fetch_flights('arrival')
        
        count = len([f for f in arrivals if f['time'] < get_spokane_time() + timedelta(hours=1)])
        
        strategy = "Stay Downtown"
        if count >= 2: strategy = "Moderate Demand"
        if count >= 4: strategy = "HIGH DEMAND"
        
        text = (f"STATUS: {get_spokane_time().strftime('%I:%M %p')}\n"
                f"Weather: {temp}F, {weather_desc}\n"
                f"Inbound (1h): {count} flights\n"
                f"Strategy: {strategy}")
        
        await safe_edit_message(context, update.effective_chat.id, msg.message_id, text)
    except Exception as e:
        await safe_edit_message(context, update.effective_chat.id, msg.message_id, f"Error: {e}")

async def show_arrivals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("Fetching arrivals...")
    try:
        flights = fetch_flights('arrival')
        if not flights:
            await safe_edit_message(context, update.effective_chat.id, msg.message_id, "No upcoming passenger arrivals found (or API limit reached).")
            return

        text = "UPCOMING ARRIVALS (GEG)\n"
        for f in flights[:15]: 
            text += f"\n{f['time_str']} | {f['airline']} | {f['flight_no']}\nZone: {f['zone']} | Pickup: {f['pickup_str']}\n"
            
        await safe_edit_message(context, update.effective_chat.id, msg.message_id, text)
    except Exception as e:
        await safe_edit_message(context, update.effective_chat.id, msg.message_id, f"Error: {e}")

async def show_departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("Generating graph...")
    try:
        flights = fetch_flights('departure')
        graph_img = generate_graph(flights, "Departure")
        
        if graph_img:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg.message_id)
            await update.message.reply_photo(photo=InputFile(graph_img, filename="chart.png"), caption="Departure Demand")
        else:
            await safe_edit_message(context, update.effective_chat.id, msg.message_id, "No data for graph.")
    except Exception as e:
        await safe_edit_message(context, update.effective_chat.id, msg.message_id, f"Error: {e}")

if __name__ == '__main__':
    # Start Keep-Alive Server
    threading.Thread(target=run_web_server).start()
    
    # Check Keys
    if not all([TELEGRAM_TOKEN, AVIATION_API_KEY, WEATHER_API_KEY]):
        print("CRITICAL: Missing API Keys in Environment Variables!")
    
    # Run Bot
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('status', status))
    application.add_handler(CommandHandler('arrivals', show_arrivals))
    application.add_handler(CommandHandler('departures', show_departures))
    
    print("Bot is running...")
    application.run_polling()
