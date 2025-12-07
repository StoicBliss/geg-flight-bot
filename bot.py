import logging
import os
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta, UTC # Added UTC import
from collections import Counter
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- CONFIGURATION ---
AVIATIONSTACK_KEY = os.environ.get("AVIATIONSTACK_KEY")
OPENWEATHER_KEY = os.environ.get("OPENWEATHER_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
PORT = int(os.environ.get("PORT", 8080))  # Render provides this port automatically

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

# --- DUMMY WEB SERVER (KEEPS RENDER HAPPY) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Responds to GET requests, used by UptimeRobot or manual check."""
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is running and healthy!")
        
    def do_HEAD(self):
        """Responds to HEAD requests, often used by monitoring services."""
        self.send_response(200)
        self.end_headers()

def run_web_server():
    server_address = ('0.0.0.0', PORT)
    try:
        httpd = HTTPServer(server_address, HealthCheckHandler)
        logging.info(f"Starting dummy web server on port {PORT}")
        httpd.serve_forever()
    except Exception as e:
        logging.error(f"Failed to start web server: {e}")

# --- HELPER FUNCTIONS ---
def get_weather():
    """Fetches current weather for GEG."""
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={GEG_LAT}&lon={GEG_LON}&appid={OPENWEATHER_KEY}&units=imperial"
        res = requests.get(url).json()
        if res.get('cod') != 200:
            logging.error(f"OpenWeatherMap Error: {res}")
            return "Weather unavailable."
        
        temp = res['main']['temp']
        desc = res['weather'][0]['description'].title()
        return f"{temp}°F, {desc}"
    except Exception as e:
        logging.error(f"Weather Fetch Error: {e}")
        return "Weather unavailable."

def fetch_flights(mode='departure'):
    """Fetches flight data from AviationStack."""
    try:
        url = "http://api.aviationstack.com/v1/flights"
        params = {
            'access_key': AVIATIONSTACK_KEY,
            f'{mode}_iata': 'GEG',
            'flight_status': 'scheduled',
            'limit': 100
        }
        response = requests.get(url, params=params)
        data = response.json()
        
        # Check for AviationStack API specific errors (e.g., API key, usage limit)
        if 'error' in data:
            logging.error(f"AviationStack API Error: {data['error']}")
            return []
            
        if 'data' not in data:
            return []
            
        return data['data']
    except Exception as e:
        logging.error(f"API Request Error: {e}")
        return []

def get_cached_flights(mode):
    """Implements the 30-minute cache logic."""
    now = datetime.now(UTC)
    cached_entry = cache[mode]
    
    if (cached_entry['timestamp'] is None or 
        (now - cached_entry['timestamp']) > timedelta(minutes=CACHE_DURATION_MINUTES)):
        
        logging.info(f"Cache expired for {mode}. Fetching new data from API...")
        flights = fetch_flights(mode)
        
        cache[mode] = {
            'data': flights,
            'timestamp': now
        }
    else:
        logging.info(f"Using cached data for {mode}.")
        
    return cache[mode]['data']

def filter_and_process_flights(raw_flights, mode):
    """
    Applies the 'Instant Time Filter' with a 15-minute buffer.
    Removes flights that have already departed/arrived relative to NOW.
    """
    valid_flights = []
    peak_hours = []
    
    # Use timezone-aware UTC time
    now_utc = datetime.now(UTC).replace(tzinfo=None) # Corrected datetime usage
    
    # Set the filter threshold to 15 minutes BEFORE now
    time_threshold = now_utc - timedelta(minutes=15) # 15 minute buffer added

    for flight in raw_flights:
        try:
            time_str = flight[mode]['scheduled']
            flight_dt = datetime.fromisoformat(time_str.replace('Z', '+00:00')).replace(tzinfo=None)
            
            # The Filter: If flight time is more than 15 minutes in the past, SKIP IT.
            if flight_dt < time_threshold:
                continue

            valid_flights.append({
                'time': flight_dt,
                'airline': flight['airline']['name'],
                'flight_no': flight['flight']['iata'],
                'dest_origin': flight['arrival']['airport'] if mode == 'departure' else flight['departure']['airport']
            })
            
            peak_hours.append(flight_dt.hour)
            
        except (ValueError, TypeError, KeyError):
            continue

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

    # CHECK: If raw data fetch failed (e.g., API key issue), report it.
    if not raw_data and (cache[mode]['timestamp'] is not None and (datetime.now(UTC) - cache[mode]['timestamp']).total_seconds() < 5):
        await update.message.reply_text("🚨 **API Error:** Could not retrieve flight data from AviationStack. Please check the API key, or your daily limit may be exceeded.")
        return
    
    # 3. Apply Instant Time Filter (Runs every time)
    flights, hour_counts = filter_and_process_flights(raw_data, mode)
    
    if not flights:
        await update.message.reply_text("No upcoming flights found in the filtered list (or low volume). Try again later.")
        return

    # 4. Analyze Peak Times (for Departures mainly)
    peak_msg = ""
    if mode == 'departures' and hour_counts:
        most_common = Counter(hour_counts).most_common(3)
        peak_msg = "\n📊 **Peak Departure Hours (UTC):**\n"
        for hour, count in most_common:
            peak_msg += f"• {hour}:00 - {count} flights\n"

    # 5. Format Message
    msg = f"✈️ **GEG {mode.title()}**\n"
    msg += f"🌤 {weather}\n"
    msg += f"{peak_msg}\n"
    msg += "----------------------------\n"
    
    for f in flights[:15]:
        dt_str = f['time'].strftime("%H:%M")
        msg += f"`{dt_str}` - {f['airline']} ({f['dest_origin']})\n"
        
    msg += "\n_Times are in UTC (AviationStack default)_"

    # 6. Add "Official Crosscheck" Button
    keyboard = [[InlineKeyboardButton("Verify on GEG Website", url="https://spokaneairports.net/flight-status")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=reply_markup)

async def departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_flight_data(update, 'departures')

async def arrivals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_flight_data(update, 'arrivals')

# --- MAIN ---
if __name__ == '__main__':
    # 1. Start Dummy Web Server in a background thread
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # 2. Start Bot
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('departures', departures))
    application.add_handler(CommandHandler('arrivals', arrivals))
    
    print("Bot is running...")
    application.run_polling()
