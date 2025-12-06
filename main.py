import os
import io
import requests
import pandas as pd
import matplotlib
# Set backend to 'Agg' for headless servers (Render)
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import logging
from flask import Flask
import threading

# --- CONFIGURATION ---
AVIATIONSTACK_API_KEY = os.getenv("AVIATION_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AIRPORT_IATA = 'GEG'

# --- PASSENGER AIRLINE & TERMINAL LOGIC ---
# Concourse A/B (South): Delta, United, Southwest, American
# Concourse C (North): Alaska, American (sometimes), Allegiant
PASSENGER_AIRLINES = {
    'AS': 'Zone C (Alaska)', 
    'G4': 'Zone C (Allegiant)',
    'DL': 'Zone A/B (Delta)', 
    'UA': 'Zone A/B (United)', 
    'WN': 'Zone A/B (Southwest)', 
    'AA': 'Zone A/B (American)',
    'F9': 'Zone A/B (Frontier)',
    'SY': 'Zone A/B (Sun Country)'
}

# --- FLASK KEEP-ALIVE SERVER (For Render) ---
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

# --- CACHING SETUP ---
flight_cache = {
    'departures': {'data': None, 'timestamp': None},
    'arrivals': {'data': None, 'timestamp': None}
}
CACHE_DURATION_MINUTES = 45

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚖 **GEG Pro Driver Assistant**\n\n"
        "commands:\n"
        "/graph - 📊 Demand Chart (Green=Pickups)\n"
        "/status - 🚦 Strategy & Weather\n"
        "/arrivals - 🛬 Next Pickups (w/ Zones)\n"
        "/departures - 🛫 Next Drop-offs\n"
        "/delays - ⚠️ Delay Watch"
    )

def get_weather():
    """Fetches simple weather for GEG without API key using wttr.in"""
    try:
        # Returns: "Clear +10°C"
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
    
    def get_zone_and_check_passenger(flight):
        if not flight.get('airline'): return None
        iata = flight['airline'].get('iata')
        return PASSENGER_AIRLINES.get(iata)

    for f in deps:
        if f['departure']['scheduled']:
            zone = get_zone_and_check_passenger(f)
            if zone:
                dt = datetime.fromisoformat(f['departure']['scheduled'].replace('Z', '+00:00'))
                all_flights.append({'time': dt, 'type': 'Departure', 'status': f['flight_status'], 'zone': zone})
            
    for f in arrs:
        if f['arrival']['scheduled']:
            zone = get_zone_and_check_passenger(f)
            if zone:
                dt = datetime.fromisoformat(f['arrival']['scheduled'].replace('Z', '+00:00'))
                all_flights.append({'time': dt, 'type': 'Arrival', 'status': f['flight_status'], 'zone': zone})
            
    if not all_flights: return pd.DataFrame()
    
    df = pd.DataFrame(all_flights)
    now = datetime.now(df.iloc[0]['time'].tzinfo)
    df = df[(df['time'] >= now) & (df['time'] <= now + timedelta(hours=24))]
    df['hour'] = df['time'].dt.hour
    return df

async def send_graph(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🎨 Analyzing next 24h demand...")
    df = process_data_into_df()
    if df.empty:
        await status_msg.edit_text("No passenger flights found.")
        return

    hourly = df.groupby(['hour', 'type']).size().unstack(fill_value=0)
    for col in ['Arrival', 'Departure']:
        if col not in hourly.columns: hourly[col] = 0

    plt.figure(figsize=(10, 6))
    plt.bar(hourly.index - 0.2, hourly['Departure'], width=0.4, label='Drop-offs', color='#e74c3c')
    plt.bar(hourly.index + 0.2, hourly['Arrival'], width=0.4, label='Pick-ups', color='#2ecc71')
    plt.title('GEG Driver Demand (Next 24h)')
    plt.xlabel('Hour (24h)')
    plt.ylabel('Est. Rides')
    plt.xticks(range(0, 24))
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    await update.message.reply_photo(photo=buf, caption="📊 **Green** = Pickups | **Red** = Dropoffs")
    await status_msg.delete()

async def check_delays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = process_data_into_df()
    if df.empty: return await update.message.reply_text("No data.")
    delays = df[df['status'].isin(['active', 'delayed', 'cancelled'])]
    if delays.empty: await update.message.reply_text("✅ No major passenger delays.")
    else:
        msg = "⚠️ **PASSENGER DELAYS**\n"
        for _, row in delays.iterrows(): msg += f"{row['time'].strftime('%H:%M')} - {row['status'].upper()} ({row['zone']})\n"
        await update.message.reply_text(msg)

async def driver_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    weather = get_weather()
    df = process_data_into_df()
    if df.empty: return
    
    now_hour = datetime.now().hour
    next_3 = df[(df['hour'] >= now_hour) & (df['hour'] <= now_hour + 3)]
    
    arr_c = len(next_3[(next_3['type'] == 'Arrival') & (next_3['zone'].str.contains('Zone C'))])
    arr_ab = len(next_3[(next_3['type'] == 'Arrival') & (next_3['zone'].str.contains('Zone A/B'))])
    total = arr_c + arr_ab
    
    msg = ""
    if total >= 5: msg = "🔥 **HIGH SURGE LIKELY**"
    elif total >= 3: msg = "✅ **MODERATE DEMAND**"
    else: msg = "💤 **LOW DEMAND**"
    
    strategy = "Sit in TNC Lot."
    if arr_c > arr_ab: strategy = "Expect **ALASKA** rush (North Zone C)."
    elif arr_ab > arr_c: strategy = "Expect **DELTA/UNITED** rush (South Zone A/B)."

    await update.message.reply_text(
        f"🌤 **Weather:** {weather}\n"
        f"🚦 **Next 3 Hours:** {total} Arrivals\n\n"
        f"{msg}\n"
        f"💡 **Tip:** {strategy}"
    )

async def list_flights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = 'departure' if 'departures' in update.message.text else 'arrival'
    flights = get_flight_data(mode)
    if not flights: return await update.message.reply_text("No data currently available.")
    
    valid = []
    for f in flights:
        if f[mode]['scheduled'] and f.get('airline'):
            zone = PASSENGER_AIRLINES.get(f['airline'].get('iata'))
            if zone:
                valid.append({'data': f, 'zone': zone})
    
    valid.sort(key=lambda x: x['data'][mode]['scheduled'])
    
    title = "Incoming Pickups" if mode == 'arrival' else "Departing Drop-offs"
    msg = f"**{title}**\n\n"
    
    count = 0
    for item in valid:
        if count >= 10: break
        
        f = item['data']
        zone_raw = item['zone']
        
        airline_name = f['airline']['name']
        airline_name = airline_name.replace(" Airlines", "").replace(" Air Lines", "").replace(" Inc.", "").strip()
        flight_num = f['flight']['iata']
        
        raw_time = f[mode]['scheduled']
        dt = datetime.fromisoformat(raw_time.replace('Z', '+00:00'))
        time_str = dt.strftime('%H:%M')
        
        if mode == 'arrival':
            curbside_time = dt + timedelta(minutes=20)
            curbside_str = curbside_time.strftime('%H:%M')
            simple_zone = zone_raw.split('(')[0].strip()
            
            msg += f"**{airline_name}** ({flight_num})\n"
            msg += f"Touchdown: `{time_str}` | Ready: `{curbside_str}`\n"
            msg += f"Location: {simple_zone}\n\n"
        else:
            msg += f"`{time_str}` • **{airline_name}** ({flight_num})\n"
        
        count += 1
        
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
    application.run_polling()
