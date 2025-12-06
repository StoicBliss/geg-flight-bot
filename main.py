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

# --- CONFIGURATION ---
AVIATIONSTACK_API_KEY = os.getenv("AVIATION_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AIRPORT_IATA = 'GEG'  # Spokane International Airport

# --- CACHING SETUP ---
flight_cache = {
    'departures': {'data': None, 'timestamp': None},
    'arrivals': {'data': None, 'timestamp': None}
}
CACHE_DURATION_MINUTES = 45  # Refresh data every 45 mins

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚖 **GEG Driver Assistant 2.0**\n\n"
        "commands:\n"
        "/graph - 📊 Visual Chart of Peak Hours (Best View)\n"
        "/delays - ⚠️ Check for current delays\n"
        "/status - 🚦 Driver Advice (Surge Prediction)\n"
        "/departures - Next 10 departures\n"
        "/arrivals - Next 10 arrivals"
    )

def get_flight_data(mode='departure'):
    """Fetches flight data with caching."""
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
    """Helper to merge arrivals and departures into one DataFrame."""
    deps = get_flight_data('departure')
    arrs = get_flight_data('arrival')
    
    all_flights = []
    
    # Process Departures
    for f in deps:
        if f['departure']['scheduled']:
            dt = datetime.fromisoformat(f['departure']['scheduled'].replace('Z', '+00:00'))
            status = f['flight_status']
            all_flights.append({'time': dt, 'type': 'Departure', 'status': status})
            
    # Process Arrivals
    for f in arrs:
        if f['arrival']['scheduled']:
            dt = datetime.fromisoformat(f['arrival']['scheduled'].replace('Z', '+00:00'))
            status = f['flight_status']
            all_flights.append({'time': dt, 'type': 'Arrival', 'status': status})
            
    if not all_flights:
        return pd.DataFrame()

    df = pd.DataFrame(all_flights)
    # Filter for only next 24 hours
    now = datetime.now(df.iloc[0]['time'].tzinfo)
    df = df[(df['time'] >= now) & (df['time'] <= now + timedelta(hours=24))]
    df['hour'] = df['time'].dt.hour
    return df

async def send_graph(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates a Matplotlib chart and sends it as a photo."""
    status_msg = await update.message.reply_text("🎨 Drawing flight chart...")
    
    df = process_data_into_df()
    if df.empty:
        await status_msg.edit_text("No flight data available to graph.")
        return

    # Group data
    hourly = df.groupby(['hour', 'type']).size().unstack(fill_value=0)
    # Ensure both columns exist
    for col in ['Arrival', 'Departure']:
        if col not in hourly.columns:
            hourly[col] = 0

    # Plotting
    plt.figure(figsize=(10, 6))
    plt.bar(hourly.index - 0.2, hourly['Departure'], width=0.4, label='Departures (Drop-offs)', color='#e74c3c')
    plt.bar(hourly.index + 0.2, hourly['Arrival'], width=0.4, label='Arrivals (Pick-ups)', color='#2ecc71')
    
    plt.title('GEG Airport Demand (Next 24h)')
    plt.xlabel('Hour of Day (24h)')
    plt.ylabel('Number of Flights')
    plt.xticks(range(0, 24))
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    
    # Save to buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()

    await update.message.reply_photo(photo=buf, caption="📊 **Green** = Wait at TNC Lot (Pickups)\n**Red** = Drive people TO airport (Dropoffs)")
    await status_msg.delete()

async def check_delays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checks for active delays."""
    df = process_data_into_df()
    if df.empty:
        await update.message.reply_text("No data.")
        return

    delays = df[df['status'].isin(['active', 'delayed', 'cancelled'])]
    
    if delays.empty:
        await update.message.reply_text("✅ No major delays reported currently.")
    else:
        msg = "⚠️ **DELAY REPORT** ⚠️\n\n"
        for _, row in delays.iterrows():
            t = row['time'].strftime('%H:%M')
            msg += f"• {t} {row['type']} -> {row['status'].upper()}\n"
        await update.message.reply_text(msg)

async def driver_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gives a 'Surge Score' recommendation."""
    df = process_data_into_df()
    if df.empty: return

    # Analyze next 3 hours
    now_hour = datetime.now().hour
    next_3_hours = df[(df['hour'] >= now_hour) & (df['hour'] <= now_hour + 3)]
    
    arr_count = len(next_3_hours[next_3_hours['type'] == 'Arrival'])
    dep_count = len(next_3_hours[next_3_hours['type'] == 'Departure'])
    
    # Simple Heuristic: 1 plane = ~100 potential rideshare pax (very rough)
    score = ""
    if arr_count >= 5:
        score = "🔥 **HIGH DEMAND EXPECTED**\nTNC Lot will move fast. Go now."
    elif arr_count >= 2:
        score = "✅ **MODERATE DEMAND**\nWorth waiting if queue is short."
    else:
        score = "💤 **LOW DEMAND**\nBetter to drive downtown/hotels."

    await update.message.reply_text(
        f"🚦 **Strategy for Next 3 Hours**\n"
        f"Arrivals: {arr_count} | Departures: {dep_count}\n\n"
        f"{score}"
    )

async def list_flights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists upcoming flights."""
    mode = 'departure' if 'departures' in update.message.text else 'arrival'
    flights = get_flight_data(mode)
    if not flights:
        await update.message.reply_text("No data available.")
        return

    msg = f"✈️ **Next {mode.title()}s**\n\n"
    # Filter for valid scheduled times
    valid_flights = [f for f in flights if f[mode]['scheduled']]
    # Sort and take top 10
    valid_flights.sort(key=lambda x: x[mode]['scheduled'])
    
    for f in valid_flights[:10]:
        flight_num = f['flight']['iata']
        time_full = f[mode]['scheduled']
        # Rough parsing of time
        time_str = time_full.split('T')[1][:5] 
        airline = f['airline']['name']
        msg += f"`{time_str}` - **{flight_num}** ({airline})\n"
        
    await update.message.reply_text(msg, parse_mode='Markdown')

if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('graph', send_graph))
    application.add_handler(CommandHandler('delays', check_delays))
    application.add_handler(CommandHandler('status', driver_status))
    application.add_handler(CommandHandler('departures', list_flights))
    application.add_handler(CommandHandler('arrivals', list_flights))
    
    application.run_polling()
