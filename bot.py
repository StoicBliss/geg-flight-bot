import logging
import os
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
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
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is running and healthy!")

def run_web_server():
    server_address = ('0.0.0.0', PORT)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    logging.info(f"Starting dummy web server on port {PORT}")
    httpd.serve_forever()

# --- HELPER FUNCTIONS ---
def get_weather():
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
        if 'data' not in data:
            return []
        return data['data']
    except Exception as e:
        logging.error(f"API Error: {e}")
        return []

def get_cached_flights(mode):
    now = datetime.now()
    cached_entry = cache[mode]
    
    if (cached_entry['timestamp'] is None or 
        (now - cached_entry['timestamp']) > timedelta(minutes=CACHE_DURATION_MINUTES)):
        logging.info(f"Cache expired for {mode}. Fetching new data...")
        flights = fetch_flights(mode)
        cache[mode] = {'data': flights, 'timestamp': now}
    else:
        logging.info(f"Using cached data for {mode}.")
        
    return cache[mode]['data']

def filter_and_process_flights(raw_flights, mode):
    valid_flights = []
    peak_hours = []
    now_utc = datetime.utcnow()

    for flight in raw_flights:
        try:
            time_str = flight[mode]['scheduled']
            flight_dt = datetime.fromisoformat(time_str.replace('Z', '+00:00')).replace(tzinfo=None)
            
            # INSTANT FILTER: If flight is in the past, skip it
            if flight_dt < now_utc:
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
        "/departures - View upcoming departures\n"
        "/arrivals - View upcoming arrivals\n"
    )

async def send_flight_data(update: Update, mode):
    weather = get_weather()
    raw_data = get_cached_flights(mode)
    flights, hour_counts = filter_and_process_flights(raw_data, mode)
    
    if not flights:
        await update.message.reply_text("No upcoming flights found in current cache.")
        return

    peak_msg = ""
    if mode == 'departures' and hour_counts:
        most_common = Counter(hour_counts).most_common(3)
        peak_msg = "\n📊 **Peak Hours (UTC):**\n"
        for hour, count in most_common:
            peak_msg += f"• {hour}:00 - {count} flights\n"

    msg = f"✈️ **GEG {mode.title()}**\n🌤 {weather}\n{peak_msg}\n----------------------------\n"
    for f in flights[:15]:
        dt_str = f['time'].strftime("%H:%M")
        msg += f"`{dt_str}` - {f['airline']} ({f['dest_origin']})\n"
    
    msg += "\n_Times are in UTC_"
    
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
