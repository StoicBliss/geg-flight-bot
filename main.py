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

# --- FINAL VERIFIED TERMINAL DATA (v8.1) ---
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

# Universal Google Maps Query for TNC/Cell Phone Lot
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

# --- CACHING ---
flight_cache = {
    'departures': {'data': None, 'timestamp': None},
    'arrivals': {'data': None, 'timestamp': None}
}
CACHE_DURATION_MINUTES = 30 

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- WEATHER FUNCTION (OpenWeatherMap) ---
def get_weather():
    """Fetches current weather from OpenWeatherMap using coordinates."""
    if not OPENWEATHER_API_KEY:
        logging.error("OpenWeatherMap API Key not set.")
        return "Weather unavailable (Key missing)"

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        'lat': GEG_LAT,
        'lon': GEG_LON,
        'appid': OPENWEATHER_API_KEY,
        'units': 'imperial' # Fahrenheit
    }
    
    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status() 
        data = response.json()
        
        temp = round(data['main']['temp'])
        description = data['weather'][0]['description'].title()
        
        return f"{description}, {temp}°F"
        
    except RequestException as e:
        logging.error(f"OpenWeatherMap API request failed: {e}")
        return "Weather unavailable"

# --- AVIATIONSTACK DATA FETCHING (MODIFIED) ---
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
        response = requests.get(url, params=params, timeout=10) # Added timeout
        response.raise_for_status() 
        data = response.json()
        
        if 'data' in data and data['data'] is not None:
            flight_cache[mode + 's']['data'] = data['data']
            flight_cache[mode + 's']['timestamp'] = datetime.now()
            return data['data']
        # Returns [] if data is empty but API response was successful
        return [] 
        
    except Exception as e:
        logging.error(f"Error fetching {mode} data from AviationStack: {e}")
        # Return None on API failure, distinguishing it from an empty list
        return None 

def process_data_into_df():
    # Check for API errors when fetching both datasets
    deps = get_flight_data('departure')
    arrs = get_flight_data('arrival')
    
    if deps is None or arrs is None:
        return None # Indicate API failure

    all_flights = []
    now_spokane = datetime.now(SPOKANE_TZ)
    
    def parse_and_convert(time_str):
        if not time_str: return None
        # Parse UTC time and convert to Spokane Time
        dt_utc = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        return dt_utc.astimezone(SPOKANE_TZ)

    def get_zone(flight):
        if not flight.get('airline'): return None
        return PASSENGER_AIRLINES.get(flight['airline'].get('iata'))

    for f in deps:
        dt = parse_and_convert(f['departure']['scheduled'])
        zone = get_zone(f)
        if dt and zone and dt > now_spokane:
            all_flights.append({'time': dt, 'type': 'Departure', 'status': f['flight_status'], 'zone': zone})
            
    for f in arrs:
        dt = parse_and_convert(f['arrival']['scheduled'])
        zone = get_zone(f)
        if dt and zone and dt > now_spokane:
            all_flights.append({'time': dt, 'type': 'Arrival', 'status': f['flight_status'], 'zone': zone})
            
    if not all_flights: return pd.DataFrame()
    
    df = pd.DataFrame(all_flights)
    df = df[df['time'] <= now_spokane + timedelta(hours=24)]
    df['hour'] = df['time'].dt.hour
    return df

# --- COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "GEG Pro Driver Assistant v8.1\n\n"
        "commands:\n"
        "/status - Strategy, Weather & Best Shifts\n"
        "/graph - Demand Chart\n"
        "/arrivals - Pickups (Live)\n"
        "/departures - Drop-offs (Live)\n"
        "/delays - Check for Delays\n"
        "/navigate - GPS to TNC Lot\n"
        "/refresh - Force a cache refresh" # <-- New command
    )

async def navigate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Open Google Maps (Waiting Lot)", url=TNC_LOT_MAP_URL)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Tap below to start navigation:", reply_markup=reply_markup)

# --- NEW REFRESH COMMAND ---
async def refresh_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Pass force_refresh=True to bypass cache
    global flight_cache
    
    # Clear cache timestamps
    flight_cache['arrivals']['timestamp'] = datetime.now() - timedelta(minutes=CACHE_DURATION_MINUTES + 1)
    flight_cache['departures']['timestamp'] = datetime.now() - timedelta(minutes=CACHE_DURATION_MINUTES + 1)
    
    # Attempt to fetch new data to confirm connection
    flights = get_flight_data('arrival', force_refresh=True)
    
    if flights is None:
        await update.message.reply_text("⚠️ *Cache Cleared, but Data Refresh Failed.* The AviationStack API did not respond. Try again in a few minutes.", parse_mode='Markdown')
    else:
        await update.message.reply_text("✅ *Cache Refreshed.* New flight data fetched successfully.", parse_mode='Markdown')

async def send_graph(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("Syncing with Spokane time...")
    df = process_data_into_df()
    
    if df is None:
        await status_msg.edit_text("❌ *API Connection Error*. Could not fetch real-time flight data to build the chart.")
        return
        
    if df.empty:
        await status_msg.edit_text("No upcoming passenger flights found.")
        return

    hourly = df.groupby(['hour', 'type']).size().unstack(fill_value=0)
    for col in ['Arrival', 'Departure']:
        if col not in hourly.columns: hourly[col] = 0

    hourly = hourly.sort_index()

    plt.figure(figsize=(10, 6))
    plt.bar(hourly.index - 0.2, hourly['Departure'], width=0.4, label='Drop-offs', color='#e74c3c')
    plt.bar(hourly.index + 0.2, hourly['Arrival'], width=0.4, label='Pick-ups', color='#2ecc71')
    plt.title('GEG Real-Time Demand (Pacific Time)')
    plt.xlabel('Hour of Day')
    plt.ylabel('Est. Rides')
    plt.xticks(range(0, 24))
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close()
    buf.seek(0)
    await update.message.reply_photo(photo=buf, caption="Demand Chart (Pacific Time)")
    await status_msg.delete()

async def driver_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    weather = get_weather()
    df = process_data_into_df()
    
    now_spokane = datetime.now(SPOKANE_TZ)

    if df is None: # Handle API failure
        output = f"❌ *API Connection Error*\n\n"
        output += f"Current Time: *{now_spokane.strftime('%H:%M')}*\n"
        output += f"Current Weather: {weather}\n"
        output += f"---"
        output += f"\nCould not retrieve flight data for strategy."
    
    elif df.empty: 
        output = f"*GEG DRIVER STATUS REPORT*\n\n"
        output += f"Current Time: *{now_spokane.strftime('%H:%M')}*\n"
        output += f"Current Weather: {weather}\n"
        output += f"---"
        output += f"\n*DEMAND LEVEL*\n*LOW (NO FLIGHTS)*"
        
    else:
        next_3 = df[df['time'] <= now_spokane + timedelta(hours=3)]
        arr_count = len(next_3[next_3['type'] == 'Arrival'])
        
        if arr_count >= 6: 
            msg_clean = "HIGH SURGE LIKELY"
        elif arr_count >= 3: 
            msg_clean = "MODERATE DEMAND"
        else: 
            msg_clean = "LOW DEMAND"

        # Best Shift Logic
        if not df[df['type'] == 'Arrival'].empty:
            arr_hourly = df[df['type'] == 'Arrival'].groupby('hour').size()
            top_hours = arr_hourly.nlargest(3).index.tolist()
            top_hours.sort()
            best_shift_str = ", ".join([f"{h}:00" for h in top_hours])
        else:
            best_shift_str = "None"
        
        # --- V8.1 CLEAN LAYOUT ---
        output = f"*GEG DRIVER STATUS REPORT*\n\n"
        output += f"Current Time: *{now_spokane.strftime('%H:%M')}*\n"
        output += f"Current Weather: {weather}\n"
        output += f"---"
        output += f"\n*DEMAND FORECAST*"
        output += f"\nNext 3 Hours: {arr_count} Arrivals"
        output += f"\nDEMAND LEVEL: *{msg_clean}*"
        output += f"\n---"
        output += f"\n*OPTIMAL SHIFT STRATEGY*"
        output += f"\nBest Work Hours: `{best_shift_str}`"
    
    keyboard = [[InlineKeyboardButton("Open Waiting Lot GPS", url=TNC_LOT_MAP_URL)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(output, parse_mode='Markdown', reply_markup=reply_markup)

async def check_delays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = process_data_into_df()
    
    if df is None: return await update.message.reply_text("❌ *API Connection Error*. Could not fetch real-time flight data to check delays.", parse_mode='Markdown')

    if df.empty: return await update.message.reply_text("No data.")
    
    delays = df[df['status'].isin(['active', 'delayed', 'cancelled'])]
    
    if delays.empty: return await update.message.reply_text("No delays on upcoming flights.")
    else:
        msg = "*DELAY REPORT (Pacific Time)*\n"
        for _, row in delays.iterrows(): 
            msg += f"{row['time'].strftime('%H:%M')} - *{row['status'].upper()}* ({row['zone']})\n"
        await update.message.reply_text(msg, parse_mode='Markdown')

async def list_flights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = 'departure' if 'departures' in update.message.text else 'arrival'
    
    flights = get_flight_data(mode)
    
    if flights is None: 
        # Explicit API failure message
        return await update.message.reply_text("❌ *API Connection Error*. Could not fetch real-time flight data.", parse_mode='Markdown')
    
    if not flights: 
        # Correct message for empty flight list
        return await update.message.reply_text(f"No more {mode}s scheduled for the next 24 hours.")
    
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
    
    title = "Incoming Pickups" if mode == 'arrival' else "Departing Drop-offs"
    msg = f"*{title}*\n"
    msg += f"_Current Time: {now_spokane.strftime('%H:%M')}_\n\n"
    
    last_time = None
    cluster_count = 0
    
    for item in valid[:12]:
        f = item['data']
        zone_raw = item['zone']
        dt = item['time']
        
        airline_name = f['airline']['name']
        airline_name = airline_name.replace(" Airlines", "").replace(" Air Lines", "").replace(" Inc.", "").strip()
        flight_num = f['flight']['iata']
        time_str = dt.strftime('%H:%M')
        
        if mode == 'arrival':
            if last_time and (dt - last_time < timedelta(minutes=20)):
                cluster_count += 1
            else:
                cluster_count = 1 
            
            if cluster_count == 3:
                 msg += "⚠️ *SURGE CLUSTER DETECTED* ⚠️\n\n"

            last_time = dt
            
            curbside_time = dt + timedelta(minutes=20)
            curbside_str = curbside_time.strftime('%H:%M')
            simple_zone = zone_raw.split('(')[0].strip()
            
            msg += f"*{airline_name}* ({flight_num})\n"
            msg += f"Touchdown: `{time_str}` | Ready: `{curbside_str}`\n"
            msg += f"Location: {simple_zone}\n\n"
        else:
            msg += f"`{time_str}` • *{airline_name}* ({flight_num})\n"
        
    if not valid:
        # Correct message for filtered list
        msg += "No more flights for today!"
        
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- MAIN EXECUTION ---
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
    application.add_handler(CommandHandler('refresh', refresh_cache)) # <-- Handler for new command
    application.run_polling()
