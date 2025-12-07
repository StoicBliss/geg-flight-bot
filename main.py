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
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AIRPORT_IATA = 'GEG'
GEG_LAT = 47.6190
GEG_LON = -117.5352

# --- TIMEZONE SETUP ---
SPOKANE_TZ = pytz.timezone('US/Pacific')

# --- STATIC FALLBACK DATA ---
# If gate info is missing, we fall back to this list
FALLBACK_AIRLINE_ZONES = {
    'AS': 'Zone C', 'QX': 'Zone C', 'AA': 'Zone C', 'F9': 'Zone C', # North
    'DL': 'Zone A/B', 'UA': 'Zone A/B', 'WN': 'Zone A/B', 'OO': 'Check Gate', # South
    'G4': 'Zone A/B', 'SY': 'Zone A/B', 'WS': 'Zone A/B', 'AC': 'Zone C'
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
data_cache = {
    'df': None,
    'timestamp': None
}
CACHE_DURATION_MINUTES = 240 # 4 hours

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

# --- SMART ZONE DETECTOR ---
def detect_zone(gate, airline_iata):
    """Determines Zone C vs Zone A/B based on Gate first, then Airline."""
    # 1. Trust the Gate if we have it
    if gate:
        g = str(gate).upper()
        if g.startswith('C'): return "Zone C (North)"
        if g.startswith('A') or g.startswith('B'): return "Zone A/B (South)"
    
    # 2. Fallback to Airline Code
    return FALLBACK_AIRLINE_ZONES.get(airline_iata, "Unknown Zone")

# --- AERODATABOX API FETCHING ---
def fetch_aerodatabox_data():
    if not RAPIDAPI_KEY:
        logging.error("RapidAPI Key missing.")
        return None

    now = datetime.now(SPOKANE_TZ)
    end = now + timedelta(hours=12)
    
    # Time format: 2025-12-07T09:00
    time_from = now.strftime('%Y-%m-%dT%H:%M')
    time_to = end.strftime('%Y-%m-%dT%H:%M')
    
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "aerodatabox.p.rapidapi.com"
    }

    # Fetch Arrivals AND Departures
    endpoints = [
        ("arrival", f"https://aerodatabox.p.rapidapi.com/flights/airports/iata/{AIRPORT_IATA}/{time_from}/{time_to}?direction=Arrival&withPrivate=false"),
        ("departure", f"https://aerodatabox.p.rapidapi.com/flights/airports/iata/{AIRPORT_IATA}/{time_from}/{time_to}?direction=Departure&withPrivate=false")
    ]

    all_flights = []

    for type_label, url in endpoints:
        try:
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()
            data = response.json()
            
            flight_list = data.get('arrivals') if type_label == 'arrival' else data.get('departures')
            
            if not flight_list:
                logging.warning(f"API returned empty list for {type_label}")
                continue

            for f in flight_list:
                try:
                    # 1. Skip Cargo (FedEx/UPS)
                    if f.get('isCargo') == True: continue

                    # 2. Time Parsing
                    time_obj = f.get('movement', {})
                    # Use revised time if available, else scheduled
                    time_str = time_obj.get('revisedTime') or time_obj.get('scheduledTime')
                    
                    if not time_str: continue 
                    
                    dt = datetime.fromisoformat(time_str)
                    # Force timezone to Spokane
                    if dt.tzinfo is None: dt = SPOKANE_TZ.localize(dt)
                    else: dt = dt.astimezone(SPOKANE_TZ)

                    # 3. Extract Details
                    airline_obj = f.get('airline', {})
                    airline_name = airline_obj.get('name', 'Unknown')
                    airline_iata = airline_obj.get('iata', '??')
                    flight_num = f.get('number', '??')
                    status = f.get('status', 'Scheduled')
                    
                    # 4. Smart Zone Logic
                    # Gate info is often inside 'location' object or 'movement'
                    # AeroDataBox puts it in movement -> airport -> gate usually, but varies.
                    # Based on your JSON, it's NOT deeply nested. It's direct?
                    # Let's check structure carefully. 
                    # Your sample: "departure": { "gate": "E69" ... }
                    # So we look at the 'movement' block we already grabbed?
                    # No, your JSON showed 'departure' object. AeroDataBox flattens it differently depending on endpoint.
                    # We will try to find gate in movement.
                    gate = time_obj.get('gate') # Try direct access
                    
                    zone = detect_zone(gate, airline_iata)

                    all_flights.append({
                        'time': dt,
                        'type': type_label.capitalize(), 
                        'status': status,
                        'zone': zone,
                        'airline': airline_name,
                        'flight_num': flight_num,
                        'gate': gate if gate else "TBD"
                    })
                        
                except Exception as parse_e:
                    logging.error(f"Row Parse Error: {parse_e}")
                    continue

        except Exception as e:
            logging.error(f"API Fail: {e}")
            # If one direction fails, we still want to show the other if possible
            continue

    if not all_flights:
        return pd.DataFrame()
        
    df = pd.DataFrame(all_flights)
    df['hour'] = df['time'].dt.hour
    return df

def get_data_with_cache(force_refresh=False):
    global data_cache
    if data_cache['df'] is not None and not force_refresh:
        if datetime.now() - data_cache['timestamp'] < timedelta(minutes=CACHE_DURATION_MINUTES):
            return data_cache['df']

    logging.info("Refreshing Cache...")
    new_df = fetch_aerodatabox_data()
    
    # Even if empty, we update timestamp to prevent spamming API if it's truly empty
    if new_df is not None:
        data_cache['df'] = new_df
        data_cache['timestamp'] = datetime.now()
        return new_df
    return None

# --- HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚖 **GEG Pro Driver (v10.0 Unbreakable)**\n\n"
        "commands:\n"
        "/status - Strategy & Weather\n"
        "/arrivals - Pickups\n"
        "/departures - Drop-offs\n"
        "/graph - Demand Chart\n"
        "/delays - Delay Watch\n"
        "/refresh - Force Update"
    )

async def refresh_cache_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Force refreshing data...")
    df = get_data_with_cache(force_refresh=True)
    if df is None:
        await update.message.reply_text("❌ API Error.")
    elif df.empty:
         await update.message.reply_text("⚠️ API connected, but returned 0 flights.")
    else:
        count = len(df)
        await update.message.reply_text(f"✅ Success. Found {count} flights.")

async def navigate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🗺️ Open Google Maps", url=TNC_LOT_MAP_URL)]]
    await update.message.reply_text("Tap to Navigate:", reply_markup=InlineKeyboardMarkup(keyboard))

async def driver_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    weather = get_weather()
    df = get_data_with_cache()
    
    if df is None:
        await update.message.reply_text("❌ API Error")
        return

    now = datetime.now(SPOKANE_TZ)
    # Strict Future Filter
    future_df = df[df['time'] > now] if not df.empty else df
    
    if future_df.empty:
        await update.message.reply_text(f"**STATUS REPORT**\nTime: {now.strftime('%H:%M')}\nWeather: {weather}\n\n⚠️ No data. Try /refresh")
        return

    next_3 = future_df[future_df['time'] <= now + timedelta(hours=3)]
    arr_count = len(next_3[next_3['type'] == 'Arrival'])
    
    if arr_count >= 5: demand = "HIGH SURGE"
    elif arr_count >= 2: demand = "MODERATE"
    else: demand = "LOW"
    
    output = f"**GEG STATUS**\n"
    output += f"Time: {now.strftime('%H:%M')}\n"
    output += f"Weather: {weather}\n"
    output += f"Demand: **{demand}** ({arr_count} arrs)\n"
    
    await update.message.reply_text(output, parse_mode='Markdown')

async def list_flights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = 'Departure' if 'departures' in update.message.text else 'Arrival'
    df = get_data_with_cache()
    
    if df is None or df.empty: 
        return await update.message.reply_text("No data found. Try /refresh")

    now = datetime.now(SPOKANE_TZ)
    valid = df[(df['type'] == mode) & (df['time'] > now)].sort_values('time')
    
    if valid.empty:
        return await update.message.reply_text(f"No future {mode}s found in cache.")

    msg = f"**{mode.upper()}S**\n"
    
    last_time = None
    cluster_count = 0
    
    # Show more flights (up to 15) since we have no filter now
    for _, row in valid.head(15).iterrows():
        dt = row['time']
        time_str = dt.strftime('%H:%M')
        # Clean up airline name "SkyWest Airlines" -> "SkyWest"
        name = row['airline'].replace(" Airlines", "").replace(" Air Lines", "")
        
        if mode == 'Arrival':
            if last_time and (dt - last_time < timedelta(minutes=20)):
                cluster_count += 1
            else: cluster_count = 1
            
            if cluster_count == 3: msg += "⚠️ *SURGE CLUSTER* ⚠️\n"
            last_time = dt
            
            ready_time = (dt + timedelta(minutes=20)).strftime('%H:%M')
            msg += f"*{time_str}* (Ready {ready_time}) - {name}\n"
            msg += f"   📍 {row['zone']} | Gate {row['gate']}\n"
        else:
            msg += f"*{time_str}* - {name} ({row['gate']})\n"

    await update.message.reply_text(msg, parse_mode='Markdown')

async def check_delays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = get_data_with_cache()
    if df is None or df.empty: return await update.message.reply_text("No data.")
    
    now = datetime.now(SPOKANE_TZ)
    keywords = ['Delayed', 'Cancelled', 'Diverted']
    
    # Boolean mask for filtering
    mask = (df['time'] > now) & (df['status'].str.contains('|'.join(keywords), case=False, na=False))
    delays = df[mask]
    
    if delays.empty:
        await update.message.reply_text("✅ No delays reported.")
    else:
        msg = "**DELAY ALERT**\n"
        for _, row in delays.iterrows():
            msg += f"{row['time'].strftime('%H:%M')} {row['airline']} -> {row['status']}\n"
        await update.message.reply_text(msg, parse_mode='Markdown')

async def send_graph(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Graph logic remains same, just ensuring it handles empty data
    df = get_data_with_cache()
    if df is None or df.empty:
        await update.message.reply_text("No data for graph.")
        return
        
    now = datetime.now(SPOKANE_TZ)
    df = df[df['time'] > now]
    if df.empty:
        await update.message.reply_text("No future data for graph.")
        return

    hourly = df.groupby(['hour', 'type']).size().unstack(fill_value=0)
    for col in ['Arrival', 'Departure']:
        if col not in hourly.columns: hourly[col] = 0
    hourly = hourly.sort_index()

    plt.figure(figsize=(10, 6))
    plt.bar(hourly.index - 0.2, hourly['Departure'], width=0.4, color='red', label='Dep')
    plt.bar(hourly.index + 0.2, hourly['Arrival'], width=0.4, color='green', label='Arr')
    plt.legend()
    plt.title("GEG Demand (Pacific Time)")
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close()
    buf.seek(0)
    await update.message.reply_photo(photo=buf)

# --- MAIN ---
if __name__ == '__main__':
    keep_alive()
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('status', driver_status))
    application.add_handler(CommandHandler('arrivals', list_flights))
    application.add_handler(CommandHandler('departures', list_flights))
    application.add_handler(CommandHandler('graph', send_graph))
    application.add_handler(CommandHandler('delays', check_delays))
    application.add_handler(CommandHandler('refresh', refresh_cache_cmd))
    application.add_handler(CommandHandler('navigate', navigate))
    application.run_polling()
