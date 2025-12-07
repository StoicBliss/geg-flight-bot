import logging
import os
import requests
from datetime import datetime, timedelta
from collections import Counter
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- CONFIGURATION ---
AVIATIONSTACK_KEY = os.environ.get("AVIATIONSTACK_KEY")
OPENWEATHER_KEY = os.environ.get("OPENWEATHER_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEG_LAT = "47.619"
GEG_LON = "-117.535"

# --- CACHE STORAGE ---
# Structure: {'data': [list_of_flights], 'timestamp': datetime_object}
cache = {
    'departures': {'data': [], 'timestamp': None},
    'arrivals': {'data': [], 'timestamp': None}
}

CACHE_DURATION_MINUTES = 30

# --- LOGGING ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- HELPER FUNCTIONS ---

def get_weather():
    """Fetches current weather for GEG."""
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={GEG_LAT}&lon={GEG_LON}&appid={OPENWEATHER_KEY}&units=imperial"
        res = requests.get(url).json()
        if res.get('cod') != 200:
            return "Weather unavailable."
        
        temp = res['main']['temp']
        desc = res['weather'][0]['description'].title()
        return f"{temp}°F, {desc}"
    except Exception as e:
        logging.error(f"Weather Error: {e}")
        return "Weather unavailable."

def fetch_flights(mode='departure'):
    """Fetches flight data from AviationStack."""
    try:
        url = "http://api.aviationstack.com/v1/flights"
        params = {
            'access_key': AVIATIONSTACK_KEY,
            f'{mode}_iata': 'GEG',
            'flight_status': 'scheduled',
            'limit': 100  # Max for free tier per page
        }
        response = requests.get(url, params=params)
        data = response.json()
        
        if 'data' not in data:
            return []
            
        return data['data']
    except Exception as e:
        logging.error(f"API Error: {e}")
        return []

def get_cached_flights(mode):
    """
    Implements the 30-minute cache logic.
    Returns the RAW list of flights from cache (or updates cache if expired).
    """
    now = datetime.now()
    cached_entry = cache[mode]
    
    # Check if cache is empty or expired (older than 30 mins)
    if (cached_entry['timestamp'] is None or 
        (now - cached_entry['timestamp']) > timedelta(minutes=CACHE_DURATION_MINUTES)):
        
        logging.info(f"Cache expired for {mode}. Fetching new data from API...")
        flights = fetch_flights(mode)
        
        # Save to cache
        cache[mode] = {
            'data': flights,
            'timestamp': now
        }
    else:
        logging.info(f"Using cached data for {mode}. Expires in {CACHE_DURATION_MINUTES - (now - cached_entry['timestamp']).seconds // 60} mins.")
        
    return cache[mode]['data']

def filter_and_process_flights(raw_flights, mode):
    """
    Applies the 'Instant Time Filter'.
    Removes flights that have already departed/arrived relative to NOW.
    """
    valid_flights = []
    peak_hours = []
    
    # AviationStack uses UTC usually, but 'scheduled' field often comes with offset.
    # For simplicity in this free tier script, we compare ISO strings or naive datetimes carefully.
    now_utc = datetime.utcnow()

    for flight in raw_flights:
        # Extract time
        try:
            # Determine which time field to use
            time_str = flight[mode]['scheduled']
            flight_dt = datetime.fromisoformat(time_str.replace('Z', '+00:00')).replace(tzinfo=None) # Make naive for comparison if needed
            
            # The Filter: If flight time is in the past, SKIP IT.
            # We add a small buffer (e.g., keep flights from last 15 mins) just in case, 
            # but user requested strict "remove past flights".
            if flight_dt < now_utc:
                continue

            valid_flights.append({
                'time': flight_dt,
                'airline': flight['airline']['name'],
                'flight_no': flight['flight']['iata'],
                'dest_origin': flight['arrival']['airport'] if mode == 'departure' else flight['departure']['airport']
            })
            
            # Add to peak hour counter
            peak_hours.append(flight_dt.hour)
            
        except (ValueError, TypeError, KeyError):
            continue

    # Sort by time
    valid_flights.sort(key=lambda x: x['time'])
    return valid_flights, peak_hours

# --- BOT COMMANDS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚗 **GEG Airport Driver Assistant**\n\n"
        "Commands:\n"
        "/departures - View upcoming departures & peak info\n"
        "/arrivals - View upcoming arrivals\n"
        "\nData is cached for 30 mins but filtered instantly."
    )

async def send_flight_data(update: Update, mode):
    # 1. Get Weather
    weather = get_weather()
    
    # 2. Get Cached Data (Hits API only if cache > 30m)
    raw_data = get_cached_flights(mode)
    
    # 3. Apply Instant Time Filter (Runs every time)
    flights, hour_counts = filter_and_process_flights(raw_data, mode)
    
    if not flights:
        await update.message.reply_text("No upcoming flights found in the current cache.")
        return

    # 4. Analyze Peak Times (for Departures mainly)
    peak_msg = ""
    if mode == 'departures' and hour_counts:
        # Convert UTC hours to Local (Spokane is approx UTC-7/8, strict conversion recommended for prod)
        # For simple summary we just count the raw data hours
        most_common = Counter(hour_counts).most_common(3)
        peak_msg = "\n📊 **Peak Departure Hours (UTC):**\n"
        for hour, count in most_common:
            peak_msg += f"• {hour}:00 - {count} flights\n"

    # 5. Format Message
    msg = f"✈️ **GEG {mode.title()}**\n"
    msg += f"🌤 {weather}\n"
    msg += f"{peak_msg}\n"
    msg += "----------------------------\n"
    
    # Show next 10 flights only to keep message clean
    for f in flights[:15]:
        dt_str = f['time'].strftime("%H:%M")
        msg += f"`{dt_str}` - {f['airline']} ({f['dest_origin']})\n"
        
    msg += "\n_Times are in UTC (AviationStack default)_"

    # 6. Add "Official Crosscheck" Button
    keyboard = [[InlineKeyboardButton("Verfiy on GEG Website", url="https://spokaneairports.net/flight-status")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=reply_markup)

async def departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_flight_data(update, 'departures')

async def arrivals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_flight_data(update, 'arrivals')

# --- MAIN ---
if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('departures', departures))
    application.add_handler(CommandHandler('arrivals', arrivals))
    
    print("Bot is running...")
    application.run_polling()
