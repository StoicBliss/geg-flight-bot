import logging
import os
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta, UTC
from collections import Counter, defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- CONFIGURATION ---
AVIATIONSTACK_KEY = os.environ.get("AVIATIONSTACK_KEY")
OPENWEATHER_KEY = os.environ.get("OPENWEATHER_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
PORT = int(os.environ.get("PORT", 8080))

GEG_LAT = "47.619"
GEG_LON = "-117.535"

# --- RIDESHARE INTELLIGENCE ---
# Approximate seat counts for common aircraft at GEG (Alaska, Southwest, Delta, United)
AIRCRAFT_SEATS = {
    'B737': 160, 'B738': 175, 'B739': 179, 'B38M': 178, # Boeings
    'A320': 150, 'A319': 128, 'A321': 190,              # Airbus
    'E75L': 76, 'E175': 76, 'CRJ7': 70, 'CRJ9': 76,     # Regional Jets (Horizon/SkyWest)
    'DH8D': 76, 'Q400': 76                              # Props
}
DEFAULT_SEATS = 100  # Fallback average if unknown

# --- CACHE STORAGE ---
cache = {
    'departures': {'data': [], 'timestamp': None},
    'arrivals': {'data': [], 'timestamp': None}
}
CACHE_DURATION_MINUTES = 30

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- DUMMY WEB SERVER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active.")
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_web_server():
    server_address = ('0.0.0.0', PORT)
    try:
        httpd = HTTPServer(server_address, HealthCheckHandler)
        httpd.serve_forever()
    except Exception as e:
        logging.error(f"Server error: {e}")

# --- HELPER FUNCTIONS ---
def get_weather():
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={GEG_LAT}&lon={GEG_LON}&appid={OPENWEATHER_KEY}&units=imperial"
        res = requests.get(url).json()
        if res.get('cod') != 200: return "Weather unavailable."
        return f"{res['main']['temp']:.0f}°F, {res['weather'][0]['main']}"
    except:
        return "N/A"

def fetch_flights(mode='departure'):
    try:
        url = "http://api.aviationstack.com/v1/flights"
        params = {
            'access_key': AVIATIONSTACK_KEY,
            f'{mode}_iata': 'GEG',
            'limit': 100
        }
        # Note: Removing 'flight_status'='scheduled' filter to catch Delays/Cancellations too
        response = requests.get(url, params=params)
        data = response.json()
        return data.get('data', [])
    except Exception as e:
        logging.error(f"API Error: {e}")
        return []

def get_cached_flights(mode):
    now = datetime.now(UTC)
    if (cache[mode]['timestamp'] is None or 
        (now - cache[mode]['timestamp']) > timedelta(minutes=CACHE_DURATION_MINUTES)):
        logging.info(f"Refreshing {mode} cache...")
        flights = fetch_flights(mode)
        if flights: 
            cache[mode] = {'data': flights, 'timestamp': now}
    return cache[mode]['data']

def process_flight_data(raw_flights, mode):
    valid_flights = []
    pax_volume = defaultdict(int)
    now_utc = datetime.now(UTC).replace(tzinfo=None)
    threshold = now_utc - timedelta(minutes=20) # 20 min buffer

    for f in raw_flights:
        try:
            # 1. Parse Time
            time_str = f[mode]['scheduled']
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00')).replace(tzinfo=None)
            
            if dt < threshold: continue

            # 2. Get Status & Airline
            status = f['flight_status']
            airline = f['airline']['name']
            
            # Filter out Cargo (FedEx/UPS/Empire often carry cargo)
            if "FedEx" in airline or "UPS" in airline or "Empire" in airline:
                continue

            # 3. Estimate Passengers
            # Access nested keys safely
            iata_code = "Unknown"
            if f.get('aircraft'):
                iata_code = f['aircraft'].get('iata', 'Unknown')
            
            seats = AIRCRAFT_SEATS.get(iata_code, DEFAULT_SEATS)

            # 4. Status Icons
            icon = "🟢" # Scheduled/Active
            if status == 'cancelled': icon = "⚫ (CXLD)"
            elif status == 'delayed': icon = "🔴 (DLYD)"
            elif status == 'landed': icon = "🛬"
            
            # 5. Add to list
            valid_flights.append({
                'time': dt,
                'airline': airline,
                'dest_origin': f['arrival']['airport'] if mode == 'departure' else f['departure']['airport'],
                'seats': seats,
                'status_icon': icon,
                'status_text': status
            })

            # 6. Aggregate Volume (Only if not cancelled)
            if status != 'cancelled':
                pax_volume[dt.hour] += seats

        except (ValueError, TypeError, KeyError):
            continue

    valid_flights.sort(key=lambda x: x['time'])
    return valid_flights, pax_volume

# --- COMMANDS ---

async def send_dashboard(update: Update, mode):
    raw = get_cached_flights(mode)
    if not raw:
        await update.message.reply_text("⏳ Initializing... (Fetching data, try again in 10s)")
        return

    flights, pax_volume = process_flight_data(raw, mode)
    if not flights:
        await update.message.reply_text("No relevant passenger flights found in the upcoming window.")
        return

    # --- BUILD THE DASHBOARD ---
    weather = get_weather()
    
    # Header
    title = "🛫 DEPARTURES" if mode == 'departure' else "🛬 ARRIVALS"
    msg = f"{title} | GEG | 🌡 {weather}\n"
    msg += "──────────────────\n"

    # Volume Analysis (The "Money" Section)
    msg += "💰 **DEMAND FORECAST (UTC)**\n"
    sorted_hours = sorted(pax_volume.items())[:3] # Next 3 active hours
    if sorted_hours:
        for hour, count in sorted_hours:
            # Heatmap logic
            fire = "🔥" if count > 400 else "⚡" if count > 200 else "💤"
            msg += f"`{hour:02}:00` ➜ ~{count} Pax {fire}\n"
    else:
        msg += "Low volume detected.\n"
    
    msg += "──────────────────\n"
    msg += "🕒 **FLIGHT SCHEDULE**\n"

    # Flight List
    for f in flights[:12]:
        time_display = f['time'].strftime("%H:%M")
        msg += f"{f['status_icon']} `{time_display}` **{f['airline']}**\n"
        msg += f"   └ {f['dest_origin']} (~{f['seats']} pax)\n"

    msg += "\n_Times in UTC. 🔴=Delayed, ⚫=Cancelled_"
    
    # Buttons
    kb = [[InlineKeyboardButton("Check Official GEG Site", url="https://spokaneairports.net/flight-status")]]
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚕 **GEG Driver Pro**\n\nTap /arrivals to see where the money is.\nTap /departures to catch drop-offs.")

async def departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_dashboard(update, 'departure')

async def arrivals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_dashboard(update, 'arrival')

# --- RUN ---
if __name__ == '__main__':
    threading.Thread(target=run_web_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('departures', departures))
    app.add_handler(CommandHandler('arrivals', arrivals))
    app.run_polling()
