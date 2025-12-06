import os
import io
import requests
import pandas as pd
import matplotlib
# Set backend to 'Agg' for headless servers (Render)
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import pytz  # <--- New Timezone Library
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
import logging
from flask import Flask
import threading

# --- CONFIGURATION ---
AVIATIONSTACK_API_KEY = os.getenv("AVIATION_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AIRPORT_IATA = 'GEG'

# --- TIMEZONE SETUP ---
# Forces the bot to think in Spokane time, not Server time.
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

TNC_LOT_MAP_URL = "https://www.google.com/maps/search/?api=1&query=Spokane+International+Airport+Cell+Phone+Lot"

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
CACHE_DURATION_MINUTES = 30 # Reduced to 30 mins for fresher data

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚖 **GEG Driver Assistant (Real-Time)**\n\n"
        "commands:\n"
        "/status - 🚦 Strategy & Best Shifts\n"
        "/arrivals - 🛬 Pickups (Live)\n"
        "/departures - 🛫 Drop-offs (Live)\n"
        "/graph - 📊 Demand Chart\n"
        "/navigate - 🗺️ GPS to Lot"
    )

async def navigate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🗺️ Open Google Maps (Waiting Lot)", url=TNC_LOT_MAP_URL)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Tap below to start navigation:", reply_markup=reply_markup)

def get_weather():
    try:
        response = requests.get("https://wttr.in/GEG?format=%C+%t")
        return response.text.strip()
    except:
        return "Weather unavailable"

def get_flight_data(mode='departure'):
    global flight_cache
    cached = flight_cache[mode + 's']
    if cached['data'] is not None and cached['timestamp']:
        if datetime.now() - cached['timestamp'] < timedelta(minutes=CACHE_DURATION_MINUTES):
            logging.info(f"Returning cached {mode} data.")
            return cached['data']

    url = "http://api.aviationstack.com/v1/flights"
    params = {
        'access_key': AVIATIONSTACK_API_KEY,
        'dep_iata' if mode == 'departure' else 'arr_iata': AIRPORT_IATA,
    }
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        if 'data' in data:
            flight_cache[mode + 's']['data'] = data['data']
            flight_cache[mode + 's']['timestamp'] = datetime.now()
            return data['data']
        return []
    except Exception as e:
        logging.error(f"Error fetching data: {e}")
        return []

def process_data_into_df():
    deps = get_flight_data('departure')
    arrs = get_flight_data('arrival')
    
    all_flights = []
    
    # Get Current Time in Spokane
    now_spokane = datetime.now(SPOKANE_TZ)
    
    def parse_and_convert(time_str):
        if not time_str: return None
        # 1. Parse API time (which is UTC)
        dt_utc = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        # 2. Convert to Spokane Time
        return dt_utc.astimezone(SPOKANE_TZ)

    def get_zone(flight):
        if not flight.get('airline'): return None
        return PASSENGER_AIRLINES.get(flight['airline'].get('iata'))

    for f in deps:
        dt = parse_and_convert(f['departure']['scheduled'])
        zone = get_zone(f)
        # Filter: Must have time, be a passenger airline, AND be in the future
        if dt and zone and dt > now_spokane:
            all_flights.append({'time': dt, 'type': 'Departure', 'status': f['flight_status'], 'zone': zone})
            
    for f in arrs:
        dt = parse_and_convert(f['arrival']['scheduled'])
        zone = get_zone(f)
        # Filter: Must have time, be a passenger airline, AND be in the future
        if dt and zone and dt > now_spokane:
            all_flights.append({'time': dt, 'type': 'Arrival', 'status': f['flight_status'], 'zone': zone})
            
    if not all_flights: return pd.DataFrame()
    
    df = pd.DataFrame(all_flights)
    # Double check filter (Next 24h only)
    df = df[df['time'] <= now_spokane + timedelta(hours=24)]
    df['hour'] = df['time'].dt.hour
    return df

async def send_graph(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🎨 Syncing with Spokane time...")
    df = process_data_into_df()
    if df.empty:
        await status_msg.edit_text("No upcoming passenger flights found.")
        return

    hourly = df.groupby(['hour', 'type']).size().unstack(fill_value=0)
    for col in ['Arrival', 'Departure']:
        if col not in hourly.columns: hourly[col] = 0

    # Sort index to ensure graph goes from Now -> Later
    hourly = hourly.sort_index()

    plt.figure(figsize=(10, 6))
    plt.bar(hourly.index - 0.2, hourly['Departure'], width=0.4, label='Drop-offs', color='#e74c3c')
    plt.bar(hourly.index + 0.2, hourly['Arrival'], width=0.4, label='Pick-ups', color='#2ecc71')
    plt.title('GEG Real-Time Demand (Pacific Time)')
    plt.xlabel('Hour of Day')
    plt.ylabel('Est. Rides')
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    await update.message.reply_photo(photo=buf, caption="📊 **Live Demand (Pacific Time)**")
    await status_msg.delete()

async def driver_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    weather = get_weather()
    df = process_data_into_df()
    if df.empty: 
        await update.message.reply_text("No upcoming flights found.")
        return
    
    now_hour = datetime.now(SPOKANE_TZ).hour
    # Look at next 3 hours relative to spokane time
    next_3 = df[df['time'] <= datetime.now(SPOKANE_TZ) + timedelta(hours=3)]
    arr = len(next_3[next_3['type'] == 'Arrival'])
    
    msg = "🔥 **HIGH SURGE LIKELY**" if arr >= 6 else "✅ **MODERATE**" if arr >= 3 else "💤 **LOW DEMAND**"

    # Best Shift Logic
    if not df[df['type'] == 'Arrival'].empty:
        arr_hourly = df[df['type'] == 'Arrival'].groupby('hour').size()
        top_hours = arr_hourly.nlargest(3).index.tolist()
        top_hours.sort()
        best_shift_str = ", ".join([f"{h}:00" for h in top_hours])
    else:
        best_shift_str = "None"

    keyboard = [[InlineKeyboardButton("🗺️ Nav to Waiting Lot", url=TNC_LOT_MAP_URL)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"🌤 **Weather:** {weather}\n"
        f"⌚ **Spokane Time:** {datetime.now(SPOKANE_TZ).strftime('%H:%M')}\n"
        f"🚦 **Next 3 Hours:** {arr} Arrivals\n"
        f"{msg}\n\n"
        f"💰 **Best Times Today:** {best_shift_str}",
        reply_markup=reply_markup
    )

async def check_delays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = process_data_into_df()
    if df.empty: return await update.message.reply_text("No data.")
    delays = df[df['status'].isin(['active', 'delayed', 'cancelled'])]
    if delays.empty: await update.message.reply_text("✅ No delays on upcoming flights.")
    else:
        msg = "⚠️ **DELAYS (Pacific Time)**\n"
        for _, row in delays.iterrows(): 
            msg += f"{row['time'].strftime('%H:%M')} - {row['status'].upper()} ({row['zone']})\n"
        await update.message.reply_text(msg)

async def list_flights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = 'departure' if 'departures' in update.message.text else 'arrival'
    
    # 1. Get raw data
    flights = get_flight_data(mode)
    if not flights: return await update.message.reply_text("No data currently available.")
    
    # 2. Process & Filter in Real-Time
    valid = []
    now_spokane = datetime.now(SPOKANE_TZ)
    
    for f in flights:
        if f[mode]['scheduled'] and f.get('airline'):
            zone = PASSENGER_AIRLINES.get(f['airline'].get('iata'))
            if zone:
                # Convert to Pacific Time
                dt_utc = datetime.fromisoformat(f[mode]['scheduled'].replace('Z', '+00:00'))
                dt_local = dt_utc.astimezone(SPOKANE_TZ)
                
                # STRICT FILTER: Is this flight in the future?
                if dt_local > now_spokane:
                    valid.append({'data': f, 'zone': zone, 'time': dt_local})
    
    # 3. Sort by Time
    valid.sort(key=lambda x: x['time'])
    
    title = "Incoming Pickups" if mode == 'arrival' else "Departing Drop-offs"
    msg = f"**{title}**\n"
    msg += f"⌚ _Current Time: {now_spokane.strftime('%H:%M')}_\n\n"
    
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
            # Check for clusters (within 20 mins)
            if last_time and (dt - last_time < timedelta(minutes=20)):
                cluster_count += 1
            else:
                cluster_count = 1 
            
            if cluster_count == 3:
                 msg += "⚡️ **SURGE CLUSTER DETECTED** ⚡️\n\n"

            last_time = dt
            
            curbside_time = dt + timedelta(minutes=20)
            curbside_str = curbside_time.strftime('%H:%M')
            simple_zone = zone_raw.split('(')[0].strip()
            
            msg += f"**{airline_name}** ({flight_num})\n"
            msg += f"Touchdown: `{time_str}` | Ready: `{curbside_str}`\n"
            msg += f"Location: {simple_zone}\n\n"
        else:
            msg += f"`{time_str}` • **{airline_name}** ({flight_num})\n"
        
    if not valid:
        msg += "No more flights for today!"
        
    await update.message.reply_text(msg, parse_mode='Markdown')

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
    application.run_polling()
