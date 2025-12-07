import os
import io
import requests
from requests.exceptions import RequestException
import pandas as pd
import matplotlib
# Set backend to 'Agg' for headless servers (Render)
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import logging
from flask import Flask
import threading

# --- CONFIGURATION ---
AVIATIONSTACK_API_KEY = os.getenv("AVIATION_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AIRPORT_IATA = 'GEG'
GEG_LAT = 47.6190
GEG_LON = -117.5352

# --- TIMEZONE SETUP ---
SPOKANE_TZ = pytz.timezone('US/Pacific')

# --- VERIFIED TERMINAL DATA ---
PASSENGER_AIRLINES = {
    'AS': 'Zone C (Alaska)', 
    'AA': 'Zone C (American)', 
    'F9': 'Zone C (Frontier)', 
    'DL': 'Zone A/B (Delta)', 
    'UA': 'Zone A/B (United)', 
    'WN': 'Zone A/B (Southwest)', 
    'G4': 'Zone A/B (Allegiant)',
    'SY': 'Zone A/B (Sun Country)'
}

# TNC Waiting Lot Location
TNC_LOT_MAP_URL = "https://www.google.com/maps/search/?api=1&query=Spokane+International+Airport+Cell+Phone+Waiting+Lot"

# --- FLASK KEEP-ALIVE ---
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()

# --- CACHING (Set to 8 hours to save Free Tier credits) ---
flight_cache = {
    'departures': {'data': None, 'timestamp': None},
    'arrivals': {'data': None, 'timestamp': None}
}
# 480 Minutes = 8 Hours. 
# This limits you to ~3 updates/day automatically, saving your 100/mo quota.
CACHE_DURATION_MINUTES = 480 

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- WEATHER FUNCTION (OpenWeatherMap - Keep this, it works) ---
def get_weather():
    if not OPENWEATHER_API_KEY:
        return "Weather unavailable (Key missing)"

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {'lat': GEG_LAT, 'lon': GEG_LON, 'appid': OPENWEATHER_API_KEY, 'units': 'imperial'}
    
    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status() 
        data = response.json()
        temp = round(data['main']['temp'])
        desc = data['weather'][0]['description'].title()
        return f"{desc}, {temp}°F"
    except Exception as e:
        logging.error(f"Weather API Error: {e}")
        return "Weather unavailable"

# --- AVIATIONSTACK DATA FETCHING (Restored) ---
def get_flight_data(mode='departure', force_refresh=False):
    global flight_cache
    cached = flight_cache[mode + 's']
    
    if cached['data'] is not None and cached['timestamp'] and not force_refresh:
        if datetime.now() - cached['timestamp'] < timedelta(minutes=CACHE_DURATION_MINUTES):
            logging.info(f"Returning cached {mode} data.")
            return cached['data']

    url = "http://api.aviationstack.com/v1/flights"
    params = {
        'access_key': AVIATIONSTACK_API_KEY,
        'dep_iata' if mode == 'departure' else 'arr_iata': AIRPORT_IATA,
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status() 
        data = response.json()
        
        if 'data' in data:
            flight_cache[mode + 's']['data'] = data['data']
            flight_cache[mode + 's']['timestamp'] = datetime.now()
            return data['data']
        return []
    except Exception as e:
        logging.error(f"AviationStack Error: {e}")
        return None

def process_data_into_df():
    deps = get_flight_data('departure')
    arrs = get_flight_data('arrival')
    
    if deps is None or arrs is None:
        return None

    all_flights = []
    now_spokane = datetime.now(SPOKANE_TZ)
    
    def parse_time(time_str):
        if not time_str: return None
        # Parse UTC and convert to Spokane
        dt_utc = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        return dt_utc.astimezone(SPOKANE_TZ)

    def get_zone(flight):
        if not flight.get('airline'): return None
        return PASSENGER_AIRLINES.get(flight['airline'].get('iata'))

    for f in deps:
        dt = parse_time(f['departure']['scheduled'])
        zone = get_zone(f)
        if dt and zone and dt > now_spokane:
            all_flights.append({'time': dt, 'type': 'Departure', 'status': f['flight_status'], 'zone': zone})
            
    for f in arrs:
        dt = parse_time(f['arrival']['scheduled'])
        zone = get_zone(f)
        if dt and zone and dt > now_spokane:
            all_flights.append({'time': dt, 'type': 'Arrival', 'status': f['flight_status'], 'zone': zone})
            
    if not all_flights: return pd.DataFrame()
    
    df = pd.DataFrame(all_flights)
    df = df[df['time'] <= now_spokane + timedelta(hours=24)]
    df['hour'] = df['time'].dt.hour
    return df

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚖 **GEG Pro Driver (Reverted)**\n\n"
        "commands:\n"
        "/status - Strategy & Weather\n"
        "/arrivals - Pickups\n"
        "/departures - Drop-offs\n"
        "/graph - Demand Chart\n"
        "/delays - Delay Watch\n"
        "/navigate - GPS\n"
        "/refresh - Force Update (Use sparingly!)"
    )

async def refresh_cache_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Checking AviationStack...")
    # Force refresh
    res = get_flight_data('arrival', force_refresh=True)
    if res is None:
        await update.message.reply_text("❌ API Error (Check Limits)")
    else:
        await update.message.reply_text("✅ Data Refreshed")

async def navigate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Open Google Maps", url=TNC_LOT_MAP_URL)]]
    await update.message.reply_text("Navigate:", reply_markup=InlineKeyboardMarkup(keyboard))

async def driver_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    weather = get_weather()
    df = process_data_into_df()
    
    now_spokane = datetime.now(SPOKANE_TZ)

    if df is None: 
        await update.message.reply_text(f"❌ **API Error**\nWeather: {weather}")
        return
    
    if df.empty: 
        await update.message.reply_text(f"**STATUS**\nTime: {now_spokane.strftime('%H:%M')}\nWeather: {weather}\n\nNo flights found (Check /refresh)")
        return
    
    next_3 = df[df['time'] <= now_spokane + timedelta(hours=3)]
    arr_count = len(next_3[next_3['type'] == 'Arrival'])
    
    if arr_count >= 6: demand = "HIGH SURGE"
    elif arr_count >= 3: demand = "MODERATE"
    else: demand = "LOW"

    if not df[df['type'] == 'Arrival'].empty:
        arr_hourly = df[df['type'] == 'Arrival'].groupby('hour').size()
        top_hours = arr_hourly.nlargest(3).index.tolist()
        top_hours.sort()
        best_time = ", ".join([f"{h}:00" for h in top_hours])
    else:
        best_time = "None"
    
    output = f"**GEG STATUS**\n"
    output += f"Time: {now_spokane.strftime('%H:%M')}\n"
    output += f"Weather: {weather}\n"
    output += f"Demand: **{demand}** ({arr_count} arrs)\n"
    output += f"Best Hours: `{best_time}`"
    
    await update.message.reply_text(output, parse_mode='Markdown')

async def list_flights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = 'departure' if 'departures' in update.message.text else 'arrival'
    flights = get_flight_data(mode)
    
    if flights is None: return await update.message.reply_text("❌ API Error")
    if not flights: return await update.message.reply_text(f"No {mode}s found.")
    
    valid = []
    now_spokane = datetime.now(SPOKANE_TZ)
    
    for f in flights:
        if f[mode]['scheduled'] and f.get('airline'):
            zone = PASSENGER_AIRLINES.get(f['airline'].get('iata'))
            if zone:
                dt_utc = datetime.fromisoformat(f[mode]['scheduled'].replace('Z', '+00:00'))
                dt_local = dt_utc.astimezone(SPOKANE_TZ)
                
                if dt_local > now_spokane:
                    valid.append({'data': f, 'zone': zone, 'time': dt_local})
    
    valid.sort(key=lambda x: x['time'])
    
    title = "Pickups" if mode == 'arrival' else "Drop-offs"
    msg = f"**{title}**\n"
    
    last_time = None
    cluster_count = 0
    
    for item in valid[:15]:
        f = item['data']
        dt = item['time']
        
        name = f['airline']['name'].replace(" Airlines", "").replace(" Air Lines", "").replace(" Inc.", "")
        num = f['flight']['iata']
        time_str = dt.strftime('%H:%M')
        
        if mode == 'arrival':
            if last_time and (dt - last_time < timedelta(minutes=20)):
                cluster_count += 1
            else: cluster_count = 1
            
            if cluster_count == 3: msg += "⚠️ *SURGE CLUSTER* ⚠️\n"
            last_time = dt
            
            ready_time = (dt + timedelta(minutes=20)).strftime('%H:%M')
            msg += f"*{time_str}* (Ready {ready_time}) - {name}\n"
            msg += f"   📍 {item['zone']}\n"
        else:
            msg += f"*{time_str}* - {name} ({num})\n"
        
    await update.message.reply_text(msg, parse_mode='Markdown')

async def check_delays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = process_data_into_df()
    if df is None: return await update.message.reply_text("❌ API Error")
    if df.empty: return await update.message.reply_text("No data.")
    
    delays = df[df['status'].isin(['active', 'delayed', 'cancelled'])]
    if delays.empty: return await update.message.reply_text("✅ No delays.")
    else:
        msg = "**DELAY REPORT**\n"
        for _, row in delays.iterrows(): 
            msg += f"{row['time'].strftime('%H:%M')} - {row['status']} ({row['zone']})\n"
        await update.message.reply_text(msg, parse_mode='Markdown')

async def send_graph(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = process_data_into_df()
    if df is None or df.empty:
        await update.message.reply_text("No data.")
        return

    hourly = df.groupby(['hour', 'type']).size().unstack(fill_value=0)
    for col in ['Arrival', 'Departure']:
        if col not in hourly.columns: hourly[col] = 0
    hourly = hourly.sort_index()

    plt.figure(figsize=(10, 6))
    plt.bar(hourly.index - 0.2, hourly['Departure'], width=0.4, color='red', label='Dep')
    plt.bar(hourly.index + 0.2, hourly['Arrival'], width=0.4, color='green', label='Arr')
    plt.legend()
    plt.title('GEG Demand (Pacific)')
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close()
    buf.seek(0)
    await update.message.reply_photo(photo=buf)

if __name__ == '__main__':
    keep_alive()
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('graph', send_graph))
    application.add_handler(CommandHandler('delays', check_delays))
    application.add_handler(CommandHandler('status', driver_status))
    application.add_handler(CommandHandler('departures', list_flights))
    application.add_handler(CommandHandler('arrivals', list_flights))
    application.add_handler(CommandHandler('navigate', navigate))
    application.add_handler(CommandHandler('refresh', refresh_cache_cmd))
    application.run_polling()
