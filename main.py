import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import logging

# --- CONFIGURATION ---
AVIATIONSTACK_API_KEY = os.getenv("AVIATION_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AIRPORT_IATA = 'GEG'  # Spokane International Airport

# --- CACHING SETUP ---
# We cache data to save API credits (AviationStack free tier is limited)
flight_cache = {
    'departures': {'data': None, 'timestamp': None},
    'arrivals': {'data': None, 'timestamp': None}
}
CACHE_DURATION_MINUTES = 60 

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚖 **Spokane Airport (GEG) Driver Bot**\n\n"
        "I track peak flight times to help you plan your rides.\n\n"
        "commands:\n"
        "/departures - Next 10 scheduled departures\n"
        "/arrivals - Next 10 scheduled arrivals\n"
        "/peak - Show hourly passenger demand (Best for planning!)"
    )

def get_flight_data(mode='departure'):
    """Fetches flight data with caching."""
    global flight_cache
    
    # Check cache first
    cached = flight_cache[mode + 's']
    if cached['data'] is not None and cached['timestamp']:
        if datetime.now() - cached['timestamp'] < timedelta(minutes=CACHE_DURATION_MINUTES):
            logging.info(f"Returning cached {mode} data.")
            return cached['data']

    # Fetch from API
    url = "http://api.aviationstack.com/v1/flights"
    params = {
        'access_key': AVIATIONSTACK_API_KEY,
        'dep_iata' if mode == 'departure' else 'arr_iata': AIRPORT_IATA,
        'flight_status': 'scheduled'
    }
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        if 'data' in data:
            # Update cache
            flight_cache[mode + 's']['data'] = data['data']
            flight_cache[mode + 's']['timestamp'] = datetime.now()
            return data['data']
        else:
            return []
    except Exception as e:
        logging.error(f"Error fetching data: {e}")
        return []

async def peak(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Analyzes flights to find peak hours for the next 24h."""
    status_msg = await update.message.reply_text("🔄 Crunching flight data...")
    
    deps = get_flight_data('departure')
    arrs = get_flight_data('arrival')
    
    if not deps and not arrs:
        await status_msg.edit_text("❌ Could not fetch flight data. API limit might be reached.")
        return

    # Process data into a DataFrame
    all_flights = []
    
    for f in deps:
        if f['departure']['scheduled']:
            dt = datetime.fromisoformat(f['departure']['scheduled'].replace('Z', '+00:00'))
            all_flights.append({'time': dt, 'type': 'Departure (Drop-offs)'})
            
    for f in arrs:
        if f['arrival']['scheduled']:
            dt = datetime.fromisoformat(f['arrival']['scheduled'].replace('Z', '+00:00'))
            all_flights.append({'time': dt, 'type': 'Arrival (Pick-ups)'})
            
    df = pd.DataFrame(all_flights)
    
    if df.empty:
        await status_msg.edit_text("No scheduled flights found in data.")
        return

    # Convert to local time (assuming server is UTC, adjust if needed)
    # Ideally, convert to US/Pacific timezone here
    
    df['hour'] = df['time'].dt.hour
    hourly_counts = df.groupby(['hour', 'type']).size().unstack(fill_value=0)
    
    # Build the text graph
    report = "📊 **GEG Peak Hours (Next 24h)**\n\n"
    
    # Simple text graph
    for hour in range(24):
        if hour in hourly_counts.index:
            d_count = hourly_counts.loc[hour].get('Departure (Drop-offs)', 0)
            a_count = hourly_counts.loc[hour].get('Arrival (Pick-ups)', 0)
            
            if d_count + a_count == 0:
                continue
                
            time_str = f"{hour:02d}:00"
            # Visual bars: 🛫 for departures, 🛬 for arrivals
            bar = "🛫" * int(d_count) + " " + "🛬" * int(a_count)
            report += f"`{time_str}` | {bar} ({d_count+a_count})\n"

    report += "\nKey: 🛫 = Scheduled Dep | 🛬 = Scheduled Arr"
    await status_msg.edit_text(report, parse_mode='Markdown')

async def list_flights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists upcoming flights."""
    mode = 'departure' if 'departures' in update.message.text else 'arrival'
    flights = get_flight_data(mode)
    
    if not flights:
        await update.message.reply_text("No data available.")
        return

    # Sort by time and take next 10
    # (Simple logic, can be improved with timezone awareness)
    msg = f"✈️ **Upcoming {mode.title()}s**\n\n"
    for f in flights[:10]:
        flight_num = f['flight']['iata']
        time = f[mode]['scheduled'].split('T')[1][:5]
        airline = f['airline']['name']
        msg += f"`{time}` - **{flight_num}** ({airline})\n"
        
    await update.message.reply_text(msg, parse_mode='Markdown')

if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('peak', peak))
    application.add_handler(CommandHandler('departures', list_flights))
    application.add_handler(CommandHandler('arrivals', list_flights))
    
    application.run_polling()
