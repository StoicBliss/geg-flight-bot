import logging
import os
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta, timezone
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
# Known cargo/private airlines to filter out (Bogus Info Filter)
CARGO_AIRLINES = ["FedEx", "UPS", "Empire Airlines", "Ameriflight", "Corporate Air", "Alpine Air"]

# Seat estimates for GEG aircraft
AIRCRAFT_SEATS = {
    'B737': 160, 'B738': 175, 'B739': 179, 'B38M': 178, # Boeings
    'A320': 150, 'A319': 128, 'A321': 190,              # Airbus
    'E75L': 76, 'E175': 76, 'CRJ7': 70, 'CRJ9': 76,     # Regional (Horizon/SkyWest)
    'DH8D': 76, 'Q400': 76                              # Props
}
DEFAULT_SEATS = 100

# --- CACHE STORAGE ---
# FIXED: Keys now match the singular 'mode' arguments used in functions
cache = {
    'departure': {'data': [], 'timestamp': None},
    'arrival': {'data': [], 'timestamp': None}
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
        # Fetching all statuses to catch delays/cancellations
        response = requests.get(url, params=params)
        data = response.json()
        
        if 'error' in data:
            logging.error(f"API Error: {data['error']}")
            return []
            
        return data.get('data', [])
    except Exception as e:
        logging.error(f"API Request Failed: {e}")
        return []

def get_cached_flights(mode):
    # FIXED: Using timezone-aware UTC to prevent deprecation warnings
    now = datetime.now(timezone.utc)
    
    # Check if cache is empty or expired
    if (cache[mode]['timestamp'] is None or 
        (now - cache[mode]['timestamp']) > timedelta(minutes=CACHE_DURATION_MINUTES)):
        
        logging.info(f"Refreshing {mode} cache from API...")
        flights = fetch_flights(mode)
        
        # Only update cache if we actually got data back
        if flights: 
            cache[mode] = {'data': flights, 'timestamp': now}
        elif not cache[mode]['data']: 
            logging.warning(f"API returned no data for {mode} and cache is empty.")
            
    return cache[mode]['data']

def process_flight_data(raw_flights, mode):
    valid_flights = []
    pax_volume = defaultdict(int)
    
    # FIXED: Time filtering buffer (20 mins in past)
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    threshold = now_utc - timedelta(minutes=20)

    for f in raw_flights:
        try:
            # 1. Parse Time
            time_str = f[mode]['scheduled']
            # Convert ISO format to naive datetime for comparison
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00')).replace(tzinfo=None)
            
            # Filter: Skip old flights
            if dt < threshold: continue

            # 2. Extract Details
            status = f.get('flight_status', 'scheduled')
            airline = f.get('airline', {}).get('name', 'Unknown')
            
            # --- AUTHENTICITY FILTER ---
            # Remove Cargo/Logistics flights
            if any(cargo in airline for cargo in CARGO_AIRLINES):
                continue
            
            # 3. Estimate Passengers
            iata_code = "Unknown"
            if f.get('aircraft'):
                iata_code = f['aircraft'].get('iata', 'Unknown')
            seats = AIRCRAFT_SEATS.get(iata_code, DEFAULT_SEATS)

            # 4. Status Icons
            icon = "🟢" 
            if status == 'cancelled': icon = "⚫ (CXLD)"
            elif status == 'delayed': icon = "🔴 (DLYD)"
            elif status == 'landed': icon = "🛬"
            elif status == 'active': icon = "✈️"

            # 5. Build Object
            valid_flights.append({
                'time': dt,
                'airline': airline,
                'dest_origin': f['arrival']['airport'] if mode == 'departure' else f['departure']['airport'],
                'seats': seats,
                'status_icon': icon,
                'status_text': status
            })

            # 6. Aggregate Volume (ignore cancelled)
            if status != 'cancelled':
                pax_volume[dt.hour] += seats

        except (ValueError, TypeError, KeyError) as e:
            continue

    valid_flights.sort(key=lambda x: x['time'])
    return valid_flights, pax_volume

# --- COMMANDS ---

async def send_dashboard(update: Update, mode):
    # Retrieve raw data (singular key 'departure' or 'arrival')
    raw = get_cached_flights(mode)
    
    if not raw and cache[mode]['timestamp'] is None:
        await update.message.reply_text("⚠️ **System Info:** No data in cache. Possible API limit reached or API downtime.")
        return

    flights, pax_volume = process_flight_data(raw, mode)
    
    if not flights:
        await update.message.reply_text("💤 No upcoming passenger flights found in the next few hours.")
        return

    # --- BUILD THE DASHBOARD ---
    weather = get_weather()
    
    title = "🛫 DEPARTURES" if mode == 'departure' else "🛬 ARRIVALS"
    msg = f"{title} | GEG | 🌡 {weather}\n"
    msg += "──────────────────\n"

    # Demand Forecast
    msg += "💰 **DEMAND FORECAST (UTC)**\n"
    sorted_hours = sorted(pax_volume.items())
    
    # Show only the next 3 active hours to keep it readable
    if sorted_hours:
        for hour, count in sorted_hours[:3]:
            fire = "🔥" if count > 350 else "⚡" if count > 150 else "💤"
            msg += f"`{hour:02}:00` ➜ ~{count} Pax {fire}\n"
    else:
        msg += "Low passenger volume detected.\n"
    
    msg += "──────────────────\n"
    msg += "🕒 **FLIGHT SCHEDULE**\n"

    # Flight List (Top 12)
    for f in flights[:12]:
        time_display = f['time'].strftime("%H:%M")
        msg += f"{f['status_icon']} `{time_display}` **{f['airline']}**\n"
        # Truncate long airport names for mobile view
        short_loc = (f['dest_origin'][:20] + '..') if len(f['dest_origin']) > 20 else f['dest_origin']
        msg += f"   └ {short_loc} (~{f['seats']} pax)\n"

    msg += "\n_Times are UTC. Verify delays below._"
    
    # Official Cross-Match Link
    kb = [[InlineKeyboardButton("🔍 Verify on GEG Official Site", url="https://spokaneairports.net/flight-status")]]
    
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚕 **GEG Driver Pro v3**\n\n"
        "Commands:\n"
        "/arrivals - See incoming demand (Surge Detector)\n"
        "/departures - See drop-off opportunities\n\n"
        "_Data cached for 30m. Cargo flights hidden._"
    )

async def departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_dashboard(update, 'departure')

async def arrivals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_dashboard(update, 'arrival')

# --- MAIN ---
if __name__ == '__main__':
    # Start Dummy Server for Render
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # Start Bot
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('departures', departures))
    app.add_handler(CommandHandler('arrivals', arrivals))
    
    print("Bot is running...")
    app.run_polling()
