import os
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
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY") # NEW KEY NAME
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AIRPORT_IATA = 'GEG'
GEG_LAT = 47.6190
GEG_LON = -117.5352

# --- TIMEZONE SETUP ---
SPOKANE_TZ = pytz.timezone('US/Pacific')

# --- TERMINAL DATA ---
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

# --- CACHING STRATEGY ---
# We cache the DATAFRAME directly now, not the raw JSON
data_cache = {
    'df': None,
    'timestamp': None
}
# Refresh every 4 hours (Matches 12h chunks strategy)
CACHE_DURATION_MINUTES = 240 

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- WEATHER FUNCTION ---
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
        logging.error(f"Weather Error: {e}")
        return "Weather unavailable"

# --- AERODATABOX API FETCHING (THE GURU FIX) ---
def fetch_aerodatabox_data():
    """Fetches 12-hour chunks of data for Arrivals AND Departures."""
    if not RAPIDAPI_KEY:
        logging.error("RapidAPI Key missing.")
        return None

    # We fetch a 12-hour window: Now -> Now + 12h
    # This captures the whole "shift" in one go.
    now = datetime.now(SPOKANE_TZ)
    end = now + timedelta(hours=12)
    
    # AeroDataBox format: YYYY-MM-DDTHH:MM
    time_from = now.strftime('%Y-%m-%dT%H:%M')
    time_to = end.strftime('%Y-%m-%dT%H:%M')
    
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "aerodatabox.p.rapidapi.com"
    }

    # Define endpoints (AeroDataBox separates Arrs/Deps)
    endpoints = [
        ("arrival", f"https://aerodatabox.p.rapidapi.com/flights/airports/iata/{AIRPORT_IATA}/{time_from}/{time_to}?direction=Arrival&withPrivate=false"),
        ("departure", f"https://aerodatabox.p.rapidapi.com/flights/airports/iata/{AIRPORT_IATA}/{time_from}/{time_to}?direction=Departure&withPrivate=false")
    ]

    all_flights = []

    for type_label, url in endpoints:
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            # AeroDataBox returns a list under 'arrivals' or 'departures' key
            flight_list = data.get('arrivals') if type_label == 'arrival' else data.get('departures')
            
            if not flight_list: continue

            for f in flight_list:
                # AeroDataBox Structure parsing
                try:
                    # Time Parsing (Handles "scheduled" vs "revised")
                    # We prefer 'revised' (actual time) over 'scheduled' if available
                    time_obj = f.get('movement', {})
                    
                    # Key logic: Use revised time if exists, else scheduled
                    time_str = time_obj.get('revisedTime') or time_obj.get('scheduledTime')
                    if not time_str: continue # Skip if no time
                    
                    # AeroDataBox includes timezone in string sometimes, strip it for safety or parse directly
                    # Format usually: 2025-12-07T14:00:00-08:00
                    dt = datetime.fromisoformat(time_str)
                    
                    # Convert to Spokane Time if not already
                    if dt.tzinfo is None:
                        dt = SPOKANE_TZ.localize(dt)
                    else:
                        dt = dt.astimezone(SPOKANE_TZ)

                    # Airline Info
                    airline_obj = f.get('airline', {})
                    airline_name = airline_obj.get('name', 'Unknown')
                    airline_iata = airline_obj.get('iata', '??')
                    flight_num = f.get('number', '??')
                    status = f.get('status', 'Unknown')

                    # Zone Logic
                    zone = PASSENGER_AIRLINES.get(airline_iata)
                    
                    # Strict Filter: Only whitelisted airlines
                    if zone:
                        all_flights.append({
                            'time': dt,
                            'type': type_label.capitalize(), # "Arrival" or "Departure"
                            'status': status,
                            'zone': zone,
                            'airline': airline_name,
                            'flight_num': flight_num
                        })
                except Exception as parse_e:
                    logging.error(f"Error parsing flight: {parse_e}")
                    continue

        except Exception as e:
            logging.error(f"API Request Failed for {type_label}: {e}")
            return None # Fail hard if API breaks

    # Create DataFrame
    if not all_flights:
        return pd.DataFrame()
        
    df = pd.DataFrame(all_flights)
    df['hour'] = df['time'].dt.hour
    return df

def get_data_with_cache(force_refresh=False):
    global data_cache
    
    # Check cache validity
    if data_cache['df'] is not None and not force_refresh:
        if datetime.now() - data_cache['timestamp'] < timedelta(minutes=CACHE_DURATION_MINUTES):
            logging.info("Returning cached data.")
            return data_cache['df']

    # Fetch New Data
    logging.info("Fetching fresh data from AeroDataBox...")
    new_df = fetch_aerodatabox_data()
    
    if new_df is not None:
        data_cache['df'] = new_df
        data_cache['timestamp'] = datetime.now()
        return new_df
    else:
        # If fetch failed but we have old cache, return old cache with warning? 
        # Ideally return None to signal error.
        return None

# --- HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚖 **GEG Pro Driver (AeroDataBox Edition)**\n\n"
        "commands:\n"
        "/status - Strategy & Weather\n"
        "/arrivals - Pickups\n"
        "/departures - Drop-offs\n"
        "/graph - Demand Chart\n"
        "/refresh - Force Update"
    )

async def refresh_cache_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = get_data_with_cache(force_refresh=True)
    if df is None:
        await update.message.reply_text("❌ API Error. Could not refresh.")
    else:
        await update.message.reply_text("✅ Data Refreshed Successfully.")

async def driver_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    weather = get_weather()
    df = get_data_with_cache()
    
    if df is None:
        await update.message.reply_text("❌ **API Connection Error**")
        return

    now = datetime.now(SPOKANE_TZ)
    
    # Filter for future only (Local filter)
    future_df = df[df['time'] > now] if not df.empty else df
    
    if future_df.empty:
        await update.message.reply_text(f"**STATUS REPORT**\nTime: {now.strftime('%H:%M')}\nWeather: {weather}\n\nNo upcoming flights found.")
        return

    # Next 3 hours
    next_3 = future_df[future_df['time'] <= now + timedelta(hours=3)]
    arr_count = len(next_3[next_3['type'] == 'Arrival'])
    
    if arr_count >= 6: demand = "HIGH SURGE LIKELY"
    elif arr_count >= 3: demand = "MODERATE DEMAND"
    else: demand = "LOW DEMAND"
    
    # Best Shift (Next 12h)
    arrivals_only = future_df[future_df['type'] == 'Arrival']
    if not arrivals_only.empty:
        busy_hours = arrivals_only.groupby('hour').size().nlargest(3).index.tolist()
        busy_hours.sort()
        best_time = ", ".join([f"{h}:00" for h in busy_hours])
    else:
        best_time = "None"

    output = f"**GEG DRIVER STATUS**\n\n"
    output += f"Time: **{now.strftime('%H:%M')}**\n"
    output += f"Weather: {weather}\n"
    output += f"---\n"
    output += f"**DEMAND: {demand}**\n"
    output += f"Arrivals (3h): {arr_count}\n"
    output += f"---\n"
    output += f"**BEST HOURS:** `{best_time}`"
    
    keyboard = [[InlineKeyboardButton("Open Waiting Lot GPS", url=TNC_LOT_MAP_URL)]]
    await update.message.reply_text(output, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def list_flights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = 'Departure' if 'departures' in update.message.text else 'Arrival'
    df = get_data_with_cache()
    
    if df is None: return await update.message.reply_text("❌ API Error")
    if df.empty: return await update.message.reply_text("No data.")

    now = datetime.now(SPOKANE_TZ)
    # Filter: Type + Future Time
    valid = df[(df['type'] == mode) & (df['time'] > now)].sort_values('time')
    
    if valid.empty:
        return await update.message.reply_text(f"No more {mode}s scheduled.")

    msg = f"**{mode.upper()}S**\n"
    msg += f"_Current: {now.strftime('%H:%M')}_\n\n"
    
    last_time = None
    cluster_count = 0
    
    for _, row in valid.head(12).iterrows():
        dt = row['time']
        time_str = dt.strftime('%H:%M')
        flight_num = f"{row['airline']} ({row['flight_num']})"
        
        if mode == 'Arrival':
            if last_time and (dt - last_time < timedelta(minutes=20)):
                cluster_count += 1
            else: cluster_count = 1
            if cluster_count == 3: msg += "⚠️ *SURGE CLUSTER* ⚠️\n\n"
            last_time = dt
            
            ready_time = (dt + timedelta(minutes=20)).strftime('%H:%M')
            msg += f"*{flight_num}*\nLand: `{time_str}` | Ready: `{ready_time}`\nLoc: {row['zone']}\n\n"
        else:
            msg += f"`{time_str}` • *{flight_num}*\n"

    await update.message.reply_text(msg, parse_mode='Markdown')

async def send_graph(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("Generating chart...")
    df = get_data_with_cache()
    if df is None or df.empty:
        await status_msg.edit_text("No data available.")
        return

    # Filter for future only for relevance
    now = datetime.now(SPOKANE_TZ)
    df = df[df['time'] > now]

    hourly = df.groupby(['hour', 'type']).size().unstack(fill_value=0)
    for col in ['Arrival', 'Departure']:
        if col not in hourly.columns: hourly[col] = 0
    hourly = hourly.sort_index()

    plt.figure(figsize=(10, 6))
    plt.bar(hourly.index - 0.2, hourly['Departure'], width=0.4, label='Drop-offs', color='#e74c3c')
    plt.bar(hourly.index + 0.2, hourly['Arrival'], width=0.4, label='Pick-ups', color='#2ecc71')
    plt.title('GEG Real-Time Demand (AeroDataBox)')
    plt.xlabel('Hour')
    plt.ylabel('Flights')
    plt.xticks(range(0, 24))
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close()
    buf.seek(0)
    await update.message.reply_photo(photo=buf, caption="Demand Chart")
    await status_msg.delete()

# --- MAIN ---
if __name__ == '__main__':
    keep_alive()
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('status', driver_status))
    application.add_handler(CommandHandler('arrivals', list_flights))
    application.add_handler(CommandHandler('departures', list_flights))
    application.add_handler(CommandHandler('graph', send_graph))
    application.add_handler(CommandHandler('refresh', refresh_cache_cmd))
    application.add_handler(CommandHandler('navigate', navigate)) # Added missing handler
    application.run_polling()
