import logging
import os
import time
import requests
import pandas as pd
import matplotlib.pyplot as plt
import io
import threading
from flask import Flask 
from datetime import datetime, timedelta
import pytz
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler

# --- WEB SERVER FOR RENDER (KEEPS BOT ALIVE) --- #
app = Flask(__name__)

@app.route('/')
def health_check():
    return "GEG Bot is Running!"

def run_web_server():
    # Render provides the PORT environment variable
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- CONFIGURATION --- #
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AVIATION_API_KEY = os.getenv("AVIATION_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

# Spokane Configuration
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
flight_cache = {
    "arrivals": {"data": None, "timestamp": 0},
    "departures": {"data": None, "timestamp": 0}
}
CACHE_DURATION = 1800 

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- HELPER FUNCTIONS --- #
def get_spokane_time():
    return datetime.now(TIMEZONE)

def get_weather():
    url = f"http://api.openweathermap.org/data/2.5/weather?lat=47.619&lon=-117.535&appid={WEATHER_API_KEY}&units=imperial"
    try:
        r = requests.get(url).json()
        temp = round(r['main']['temp'])
        desc = r['weather'][0]['description'].title()
        return temp, desc
    except Exception as e:
        logging.error(f"Weather API Error: {e}")
        return None, "Unavailable"

def fetch_flights(mode='arrival'):
    global flight_cache
    current_time = time.time()
    
    if flight_cache[mode]["data"] is not None and (current_time - flight_cache[mode]["timestamp"] < CACHE_DURATION):
        logging.info(f"Using cached {mode} data.")
        raw_data = flight_cache[mode]["data"]
    else:
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
            if 'data' not in data: return []
            raw_data = data['data']
            flight_cache[mode]["data"] = raw_data
            flight_cache[mode]["timestamp"] = current_time
        except Exception as e:
            logging.error(f"Aviationstack API Error: {e}")
            return []

    now = get_spokane_time()
    processed_flights = []

    for f in raw_data:
        if not f.get('airline'): continue
        airline_name = f['airline'].get('name', 'UNKNOWN')
        
        if any(banned in airline_name.upper() for banned in BANNED_CARRIERS): continue
        if airline_name not in TERMINAL_MAP: continue

        if mode == 'arrival':
            time_str = f['arrival'].get('estimated') or f['arrival'].get('scheduled')
        else:
            time_str = f['departure'].get('estimated') or f['departure'].get('scheduled')
            
        if not time_str: continue

        try:
            flight_time_utc = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            flight_time_local = flight_time_utc.astimezone(TIMEZONE)
        except ValueError: continue

        if flight_time_local < now - timedelta(minutes=1): continue
            
        zone = TERMINAL_MAP.get(airline_name, "Zone A/B (Default)")
        pickup_time = flight_time_local + timedelta(minutes=20)

        processed_flights.append({
            'airline': airline_name,
            'flight_no': f['flight'].get('iata', 'N/A'),
            'time': flight_time_local,
            'time_str': flight_time_local.strftime('%H:%M'),
            'pickup_str': pickup_time.strftime('%H:%M'),
            'zone': zone
        })

    processed_flights.sort(key=lambda x: x['time'])
    return processed_flights

def generate_graph(flights, title):
    if not flights: return None
    df = pd.DataFrame(flights)
    now = get_spokane_time()
    df = df[df['time'] < now + timedelta(hours=24)]
    df['hour'] = df['time'].apply(lambda x: x.strftime('%I %p')) 
    next_24_hours = [(now + timedelta(hours=i)).strftime('%I %p') for i in range(24)]
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

# --- BOT COMMANDS --- #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚖 **GEG Driver Assistant Online**\nUse /status, /arrivals, or /departures")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔄 Analyzing grid...")
    temp, weather_desc = get_weather()
    arrivals = fetch_flights('arrival')
    next_hour_count = len([f for f in arrivals if f['time'] < get_spokane_time() + timedelta(hours=1)])
    
    strategy = "⚪ Stay Downtown"
    score = 1
    if next_hour_count >= 2:
        strategy = "🟡 Moderate Demand"
        score = 5
    if next_hour_count >= 4:
        strategy = "🟢 HIGH DEMAND"
        score = 8
    
    if "Rain" in weather_desc or "Snow" in weather_desc:
        strategy += " (☔ Surge Likely)"
        score = min(10, score + 2)
        
    text = (f"📊 **STATUS: {get_spokane_time().strftime('%I:%M %p')}**\n"
            f"🌡️ {temp}°F, {weather_desc}\n"
            f"✈️ Next 1h: {next_hour_count} flights\n"
            f"🚦 {strategy}\n📈 Score: {score}/10")
    await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text=text, parse_mode='Markdown')

async def show_arrivals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔄 Fetching arrivals...")
    flights = fetch_flights('arrival')
    if not flights:
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="💤 No arrivals found.")
        return
    text = "🛬 **ARRIVALS**\n\n"
    for f in flights[:15]: 
        text += f"**{f['airline']}** {f['time_str']} | Flight {f['flight_no']}\n📍 {f['zone']} | 🚕 **{f['pickup_str']}**\n\n"
    await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text=text, parse_mode='Markdown')

async def show_departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔄 Generating graph...")
    flights = fetch_flights('departure')
    graph_img = generate_graph(flights, "Departure")
    if graph_img:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg.message_id)
        await update.message.reply_photo(photo=InputFile(graph_img, filename="chart.png"), caption="📊 **Departure Peaks**")
    else:
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="No departures to graph.")

# --- MAIN --- #
if __name__ == '__main__':
    # 1. Start the Fake Web Server in a separate thread
    threading.Thread(target=run_web_server).start()
    
    # 2. Start the Bot
    if not all([TELEGRAM_TOKEN, AVIATION_API_KEY, WEATHER_API_KEY]):
        print("ERROR: Missing Keys")
        exit(1)
    
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('status', status))
    application.add_handler(CommandHandler('arrivals', show_arrivals))
    application.add_handler(CommandHandler('departures', show_departures))
    
    print("Bot is running...")
    application.run_polling()
