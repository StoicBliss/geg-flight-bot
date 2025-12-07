import logging
import os
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo # Built-in Timezone support
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler

# --- CONFIGURATION ---
AVIATIONSTACK_KEY = os.environ.get("AVIATIONSTACK_KEY")
OPENWEATHER_KEY = os.environ.get("OPENWEATHER_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
PORT = int(os.environ.get("PORT", 8080))

# --- CONSTANTS ---
GEG_TZ = ZoneInfo("America/Los_Angeles") # Spokane Time
GEG_LAT = "47.619"
GEG_LON = "-117.535"

CARGO_AIRLINES = ["FedEx", "UPS", "Empire", "Ameriflight", "Corporate Air", "Alpine", "Kalitta"]

TERMINAL_MAP = {
    'Alaska Airlines': 'Zone C (North)',
    'American Airlines': 'Zone C (North)',
    'Delta Air Lines': 'Zone A/B (South)',
    'United Airlines': 'Zone A/B (South)',
    'Southwest Airlines': 'Zone A/B (South)',
    'Allegiant Air': 'Zone A/B (South)'
}

AIRCRAFT_SEATS = {
    'B737': 160, 'B738': 175, 'B739': 179, 'B38M': 178,
    'A320': 150, 'A319': 128, 'A321': 190,
    'E75L': 76, 'E175': 76, 'CRJ7': 70, 'CRJ9': 76,
    'DH8D': 76, 'Q400': 76
}
DEFAULT_SEATS = 100

# --- MEMORY ---
cache = {
    'departure': {'data': [], 'timestamp': None},
    'arrival': {'data': [], 'timestamp': None}
}

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- DUMMY SERVER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    def do_HEAD(self):
        self.send_response(200); self.end_headers()

def run_web_server():
    try: HTTPServer(('0.0.0.0', PORT), HealthCheckHandler).serve_forever()
    except: pass

# --- HELPERS ---
def get_weather():
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={GEG_LAT}&lon={GEG_LON}&appid={OPENWEATHER_KEY}&units=imperial"
        r = requests.get(url).json()
        return f"{r['main']['temp']:.0f}°F {r['weather'][0]['main']}"
    except: return "N/A"

def fetch_flights(mode):
    try:
        url = "http://api.aviationstack.com/v1/flights"
        params = {'access_key': AVIATIONSTACK_KEY, f'{mode}_iata': 'GEG', 'limit': 100}
        data = requests.get(url, params=params).json()
        return data.get('data', [])
    except Exception as e:
        logging.error(f"API Error: {e}")
        return None

def process_data(raw_data, mode):
    valid = []
    pax_total = 0
    # Current time in Spokane
    now_geg = datetime.now(GEG_TZ)
    # Filter buffer: keep flights from 30 mins ago onwards
    threshold = now_geg - timedelta(minutes=30)

    if not raw_data: return [], 0

    for f in raw_data:
        try:
            # 1. Parse Time (API is UTC)
            time_str = f[mode]['scheduled']
            utc_dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            # Convert to Spokane Time
            geg_dt = utc_dt.astimezone(GEG_TZ)
            
            if geg_dt < threshold: continue

            # 2. Extract Details
            airline = f.get('airline', {}).get('name', 'Unknown')
            if any(c in airline for c in CARGO_AIRLINES): continue
            
            flight_num = f.get('flight', {}).get('iata', 'Unknown')
            status = f.get('flight_status', 'scheduled')
            
            # 3. Logic
            iata = f.get('aircraft', {}).get('iata', 'Unknown') if f.get('aircraft') else 'Unknown'
            seats = AIRCRAFT_SEATS.get(iata, DEFAULT_SEATS)
            zone = TERMINAL_MAP.get(airline, "Zone A/B") # Default to South if unknown
            
            # 4. Ready Time Calculation
            # Arrival: Land + 30 mins
            # Departure: Show standard time
            ready_dt = geg_dt + timedelta(minutes=30) if mode == 'arrival' else geg_dt

            # 5. Icon
            icon = "🟢"
            if status == 'cancelled': icon = "⚫"
            elif status == 'delayed': icon = "🔴"
            elif status == 'landed': icon = "🛬"

            valid.append({
                'time': geg_dt,
                'ready_time': ready_dt,
                'airline': airline,
                'flight': flight_num,
                'seats': seats,
                'icon': icon,
                'zone': zone
            })
            if status != 'cancelled': pax_total += seats
            
        except: continue
        
    valid.sort(key=lambda x: x['time'])
    return valid, pax_total

# --- UI LOGIC ---

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE, mode=None):
    query = update.callback_query
    if query:
        mode = query.data.split("_")[1]
        await query.answer()

    # Cache Logic
    last_update = cache[mode]['timestamp']
    if not cache[mode]['data'] or (last_update and (datetime.now() - last_update).seconds > 3600):
        # Initial Fetch or very stale
        msg = await (query.message if query else update.message).reply_text("🔄 Updating live data...")
        raw = fetch_flights(mode)
        if raw is not None:
            cache[mode] = {'data': raw, 'timestamp': datetime.now()}
            if query: await msg.delete()
        else:
            await (query.message if query else update.message).reply_text("⚠️ API Error.")
            return

    # Process
    flights, total_pax = process_data(cache[mode]['data'], mode)
    weather = get_weather()
    current_time_str = datetime.now(GEG_TZ).strftime("%I:%M %p") # Dynamic Clock Display

    # Header
    title = "🛫 DEPARTURES" if mode == 'departure' else "🛬 ARRIVALS"
    traf_light = "🟢" if total_pax > 500 else "🟡" if total_pax > 200 else "🔴"
    
    text = f"{title} | {traf_light} Vol: ~{total_pax}\n"
    text += f"⏰ **{current_time_str}** (Spokane)\n"
    text += f"🌡 {weather}\n"
    text += "──────────────────────\n"
    
    # Terminal Table
    # Format: Icon Time Airline [Zone] Flight
    
    count = 0
    for f in flights[:10]:
        t_land = f['time'].strftime("%H:%M")
        t_ready = f['ready_time'].strftime("%H:%M")
        
        # Smart Row Formatting
        if mode == 'arrival':
            # Arrival: Show Landing -> Ready Time
            row1 = f"{f['icon']} **{t_land}** ➜ 🎒**{t_ready}**\n"
            row2 = f"   {f['airline']} ({f['flight']})\n"
            row3 = f"   └ {f['zone']} • ~{f['seats']}p\n"
        else:
            # Departure: Show Takeoff Time
            row1 = f"{f['icon']} **{t_land}** 🛫 {f['airline']}\n"
            row2 = f"   Flight {f['flight']} • {f['zone']}\n"
            row3 = ""

        text += row1 + row2 + row3
        count += 1

    if count == 0: text += "💤 No flights in immediate window.\n"
    
    text += "──────────────────────\n"
    text += "🎒 = Est. Ready Time (Land + 30m)" if mode == 'arrival' else ""

    # Buttons
    kb = [
        [InlineKeyboardButton(f"🔄 REFRESH {mode.upper()}", callback_data=f"refresh_{mode}")],
        [InlineKeyboardButton("Official GEG Site", url="https://spokaneairports.net/flight-status")]
    ]
    
    if query:
        await query.message.edit_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

async def refresh_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    mode = query.data.split("_")[1]
    raw = fetch_flights(mode)
    if raw:
        cache[mode] = {'data': raw, 'timestamp': datetime.now()}
        await dashboard(update, context, mode)
    else:
        await query.answer("API Limit Reached or Error.", show_alert=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚕 **GEG Driver Pro v5.0**\n/arrivals - Curb Ready Times\n/departures - Dropoff Times")

if __name__ == '__main__':
    threading.Thread(target=run_web_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('departures', lambda u,c: dashboard(u,c,'departure')))
    app.add_handler(CommandHandler('arrivals', lambda u,c: dashboard(u,c,'arrival')))
    app.add_handler(CallbackQueryHandler(refresh_handler))
    app.run_polling()
