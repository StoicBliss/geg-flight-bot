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

# --- FLASK KEEP-ALIVE SERVER (For Render) ---
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is alive!", 200

def run_flask():
    # Render provides a PORT environment variable. Default to 8080 if not set.
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
        "🚖 **GEG Driver Assistant**\n\n"
        "commands:\n"
        "/graph - 📊 Visual Chart (Best View)\n"
        "/delays - ⚠️ Delay Watch\n"
        "/status - 🚦 Driver Advice\n"
        "/departures - Next 10 departures\n"
        "/arrivals - Next 10 arrivals"
    )

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
    for f in deps:
        if f['departure']['scheduled']:
            dt = datetime.fromisoformat(f['departure']['scheduled'].replace('Z', '+00:00'))
            all_flights.append({'time': dt, 'type': 'Departure', 'status': f['flight_status']})
    for f in arrs:
        if f['arrival']['scheduled']:
            dt = datetime.fromisoformat(f['arrival']['scheduled'].replace('Z', '+00:00'))
            all_flights.append({'time': dt, 'type': 'Arrival', 'status': f['flight_status']})
            
    if not all_flights: return pd.DataFrame()
    df = pd.DataFrame(all_flights)
    now = datetime.now(df.iloc[0]['time'].tzinfo)
    df = df[(df['time'] >= now) & (df['time'] <= now + timedelta(hours=24))]
    df['hour'] = df['time'].dt.hour
    return df

async def send_graph(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🎨 Drawing flight chart...")
    df = process_data_into_df()
    if df.empty:
        await status_msg.edit_text("No flight data available.")
        return

    hourly = df.groupby(['hour', 'type']).size().unstack(fill_value=0)
    for col in ['Arrival', 'Departure']:
        if col not in hourly.columns: hourly[col] = 0

    plt.figure(figsize=(10, 6))
    plt.bar(hourly.index - 0.2, hourly['Departure'], width=0.4, label='Drop-offs', color='#e74c3c')
    plt.bar(hourly.index + 0.2, hourly['Arrival'], width=0.4, label='Pick-ups', color='#2ecc71')
    plt.title('GEG Airport Demand (Next 24h)')
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
    if delays.empty: await update.message.reply_text("✅ No major delays.")
    else:
        msg = "⚠️ **DELAYS**\n"
        for _, row in delays.iterrows(): msg += f"{row['time'].strftime('%H:%M')} - {row['status']}\n"
        await update.message.reply_text(msg)

async def driver_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = process_data_into_df()
    if df.empty: return
    now_hour = datetime.now().hour
    next_3 = df[(df['hour'] >= now_hour) & (df['hour'] <= now_hour + 3)]
    arr = len(next_3[next_3['type'] == 'Arrival'])
    msg = "🔥 HIGH DEMAND" if arr >= 5 else "✅ MODERATE" if arr >= 2 else "💤 LOW DEMAND"
    await update.message.reply_text(f"🚦 **Next 3 Hours:**\nArrivals: {arr}\n\n{msg}")

async def list_flights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = 'departure' if 'departures' in update.message.text else 'arrival'
    flights = get_flight_data(mode)
    if not flights: return await update.message.reply_text("No data.")
    valid = [f for f in flights if f[mode]['scheduled']]
    valid.sort(key=lambda x: x[mode]['scheduled'])
    msg = f"✈️ **Next {mode.title()}s**\n"
    for f in valid[:10]:
        msg += f"`{f[mode]['scheduled'].split('T')[1][:5]}` - {f['airline']['name']}\n"
    await update.message.reply_text(msg, parse_mode='Markdown')

if __name__ == '__main__':
    # 1. Start the fake web server so Render doesn't kill the app
    keep_alive()
    
    # 2. Start the Bot
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('graph', send_graph))
    application.add_handler(CommandHandler('delays', check_delays))
    application.add_handler(CommandHandler('status', driver_status))
    application.add_handler(CommandHandler('departures', list_flights))
    application.add_handler(CommandHandler('arrivals', list_flights))
    application.run_polling()
