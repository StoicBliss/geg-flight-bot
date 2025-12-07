import logging
import os
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler

# --- CONFIGURATION ---
AVIATIONSTACK_KEY = os.environ.get("AVIATIONSTACK_KEY")
OPENWEATHER_KEY = os.environ.get("OPENWEATHER_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
PORT = int(os.environ.get("PORT", 8080))

GEG_LAT = "47.619"
GEG_LON = "-117.535"

# --- RIDESHARE INTELLIGENCE ---
CARGO_AIRLINES = ["FedEx", "UPS", "Empire", "Ameriflight", "Corporate Air", "Alpine"]

# Terminal Logic: GEG has "North (C)" and "South (A/B)"
TERMINAL_MAP = {
    'Alaska Airlines': 'Zone C (North)',
    'American Airlines': 'Zone C (North)',
    'Frontier Airlines': 'Zone C (North)',
    'Delta Air Lines': 'Zone A/B (South)',
    'United Airlines': 'Zone A/B (South)',
    'Southwest Airlines': 'Zone A/B (South)',
    'Allegiant Air': 'Zone A/B (South)',
    'Sun Country Airlines': 'Zone A/B (South)'
}

# Seat Estimates
AIRCRAFT_SEATS = {
    'B737': 160, 'B738': 175, 'B739': 179, 'B38M': 178,
    'A320': 150, 'A319': 128, 'A321': 190,
    'E75L': 76, 'E175': 76, 'CRJ7': 70, 'CRJ9': 76,
    'DH8D': 76, 'Q400': 76
}
DEFAULT_SEATS = 100

# --- STORAGE (Memory) ---
cache = {
    'departure': {'data': [], 'timestamp': None},
    'arrival': {'data': [], 'timestamp': None}
}

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
        if res.get('cod') != 200: return "N/A"
        return f"{res['main']['temp']:.0f}°F, {res['weather'][0]['main']}"
    except:
        return "N/A"

def fetch_flights(mode):
    try:
        url = "http://api.aviationstack.com/v1/flights"
        params = {
            'access_key': AVIATIONSTACK_KEY,
            f'{mode}_iata': 'GEG',
            'limit': 100
        }
        response = requests.get(url, params=params)
        data = response.json()
        if 'error' in data:
            logging.error(f"API Error: {data['error']}")
            return None
        return data.get('data', [])
    except Exception as e:
        logging.error(f"API Request Failed: {e}")
        return None

def process_data(raw_data, mode):
    valid = []
    pax_total = 0
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    # Filter Buffer: Keep flights from 30 mins ago onwards
    threshold = now_utc - timedelta(minutes=30)
    
    if not raw_data: return [], 0

    for f in raw_data:
        try:
            # Time Parsing
            time_str = f[mode]['scheduled']
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00')).replace(tzinfo=None)
            
            if dt < threshold: continue

            # Extract Data
            airline = f.get('airline', {}).get('name', 'Unknown')
            status = f.get('flight_status', 'scheduled')
            
            # Cargo Filter
            if any(c in airline for c in CARGO_AIRLINES): continue
            
            # Flight Number (New Feature)
            flight_num = f.get('flight', {}).get('iata', 'Unknown')
            
            # Seat Est
            iata = f.get('aircraft', {}).get('iata', 'Unknown') if f.get('aircraft') else 'Unknown'
            seats = AIRCRAFT_SEATS.get(iata, DEFAULT_SEATS)
            
            # Terminal Logic
            zone = TERMINAL_MAP.get(airline, "Other")

            # Icons
            icon = "🟢"
            if status == 'cancelled': icon = "⚫ (CXLD)"
            elif status == 'delayed': icon = "🔴 (DLYD)"
            elif status == 'landed': icon = "🛬"
            
            valid.append({
                'time': dt,
                'airline': airline,
                'flight_num': flight_num, # Added
                'loc': f['arrival']['airport'] if mode == 'departure' else f['departure']['airport'],
                'seats': seats,
                'icon': icon,
                'zone': zone
            })
            
            if status != 'cancelled': pax_total += seats
            
        except: continue
        
    valid.sort(key=lambda x: x['time'])
    return valid, pax_total

# --- BOT LOGIC ---

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE, mode=None):
    # Determine mode (command vs button click)
    query = update.callback_query
    if query:
        mode = query.data.split("_")[1]
        await query.answer()
    
    # 1. Check Cache Age
    timestamp = cache[mode]['timestamp']
    age_minutes = 999
    if timestamp:
        age_minutes = (datetime.now(timezone.utc) - timestamp).total_seconds() / 60
    
    # 2. Logic: If NO data, force fetch. If data exists, SHOW IT (don't auto-refresh)
    raw = cache[mode]['data']
    
    if not raw and age_minutes > 60: # Initial Load or Stale
        msg = await (query.message if query else update.message).reply_text("🔄 Initializing data...")
        raw = fetch_flights(mode)
        if raw is not None:
            cache[mode] = {'data': raw, 'timestamp': datetime.now(timezone.utc)}
            age_minutes = 0
            if query: await msg.delete()
        else:
            await (query.message if query else update.message).reply_text("⚠️ API Error. Try again later.")
            return

    # 3. Process
    flights, total_pax = process_data(cache[mode]['data'], mode)
    weather = get_weather()
    
    # 4. Traffic Light System
    traffic = "🔴 QUIET"
    if total_pax > 500: traffic = "🟢 BUSY (SURGE)"
    elif total_pax > 250: traffic = "🟡 STEADY"

    # 5. Build Message
    title = "🛫 DEPARTURES" if mode == 'departure' else "🛬 ARRIVALS"
    text = f"{title} | 🌡 {weather}\n"
    text += f"📊 Status: {traffic}\n"
    text += f"🕒 Data Age: {int(age_minutes)} min ago\n"
    text += "──────────────────\n"
    
    count = 0
    for f in flights[:12]:
        t_display = f['time'].strftime("%H:%M")
        # Format: Icon Time Airline (Flight#) [Zone]
        # Example: 🟢 14:00 Delta (DL123) [Zone A/B]
        
        # Shorten Zone for display
        z_short = f['zone'].replace("Zone ", "").replace(" (North)", "N").replace(" (South)", "S")
        
        text += f"{f['icon']} `{t_display}` **{f['airline']}** ({f['flight_num']})\n"
        text += f"   └ {f['loc'][:18]} [{z_short}] ~{f['seats']}p\n"
        count += 1
        
    if count == 0: text += "💤 No passenger flights in this window.\n"
        
    text += "\n_Times in UTC. [CN]=North, [ABS]=South_"

    # 6. Buttons
    keyboard = [
        [InlineKeyboardButton(f"🔄 REFRESH {mode.upper()} (Spend Credit)", callback_data=f"refresh_{mode}")],
        [InlineKeyboardButton("🔍 Verify on GEG Site", url="https://spokaneairports.net/flight-status")]
    ]
    
    if query:
        await query.message.edit_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def refresh_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    mode = query.data.split("_")[1]
    
    # Force Fetch
    raw = fetch_flights(mode)
    if raw:
        cache[mode] = {'data': raw, 'timestamp': datetime.now(timezone.utc)}
        await dashboard(update, context, mode)
    else:
        await query.answer("Failed to refresh. Check API limit.", show_alert=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚕 **GEG Driver Pro v4.1**\n\n"
        "/arrivals - Incoming + Flight #'s\n"
        "/departures - Outgoing + Flight #'s\n"
        "Tap 'Refresh' to update data."
    )

async def dep_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await dashboard(update, context, 'departure')

async def arr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await dashboard(update, context, 'arrival')

# --- RUN ---
if __name__ == '__main__':
    threading.Thread(target=run_web_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('departures', dep_command))
    app.add_handler(CommandHandler('arrivals', arr_command))
    app.add_handler(CallbackQueryHandler(refresh_handler, pattern="^refresh_"))
    
    print("Bot is running...")
    app.run_polling()
