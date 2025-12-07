import logging
import os
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler

# --- CONFIGURATION ---
AVIATIONSTACK_KEY = os.environ.get("AVIATIONSTACK_KEY")
OPENWEATHER_KEY = os.environ.get("OPENWEATHER_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
PORT = int(os.environ.get("PORT", 8080))

# --- CONSTANTS ---
TARGET_IATA = "GEG"  # LOCKED to Spokane. Change to "GEC" only if you mean Cyprus.
GEG_TZ = ZoneInfo("America/Los_Angeles")
GEG_LAT = "47.619"
GEG_LON = "-117.535"

CARGO_AIRLINES = ["FedEx", "UPS", "Empire", "Ameriflight", "Corporate Air", "Alpine", "Kalitta", "DHL"]

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
        # We request data for GEG specifically
        params = {'access_key': AVIATIONSTACK_KEY, f'{mode}_iata': TARGET_IATA, 'limit': 100}
        data = requests.get(url, params=params).json()
        return data.get('data', [])
    except Exception as e:
        logging.error(f"API Error: {e}")
        return None

def process_data(raw_data, mode):
    valid = []
    pax_total = 0
    now_geg = datetime.now(GEG_TZ)
    threshold = now_geg - timedelta(minutes=30)

    if not raw_data: return [], 0

    for f in raw_data:
        try:
            # --- 1. FORCE FILTER (The Fix) ---
            # Strict check: If the API sends a flight that is NOT GEG, skip it.
            if mode == 'departure':
                if f['departure']['iata'] != TARGET_IATA: continue
            else:
                if f['arrival']['iata'] != TARGET_IATA: continue

            # --- 2. Time Parsing ---
            time_str = f[mode]['scheduled']
            utc_dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            geg_dt = utc_dt.astimezone(GEG_TZ)
            
            if geg_dt < threshold: continue

            # --- 3. Extract & Clean ---
            airline = f.get('airline', {}).get('name', 'Unknown')
            if any(c in airline for c in CARGO_AIRLINES): continue
            
            flight_num = f.get('flight', {}).get('iata', 'Unknown')
            status = f.get('flight_status', 'scheduled')
            
            # --- 4. Logic ---
            seats = AIRCRAFT_SEATS.get(f.get('aircraft', {}).get('iata', 'Unknown'), DEFAULT_SEATS)
            zone = TERMINAL_MAP.get(airline, "Zone A/B")
            
            ready_dt = geg_dt + timedelta(minutes=30) if mode == 'arrival' else geg_dt

            # --- 5. Icon ---
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
            
        except Exception as e:
            continue
        
    valid.sort(key=lambda x: x['time'])
    return valid, pax_total

# --- UI LOGIC ---

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE, mode=None):
    query = update.callback_query
    if query: mode = query.data.split("_")[1]; await query.answer()

    # Cache Check
    last_update = cache[mode]['timestamp']
    if not cache[mode]['data'] or (last_update and (datetime.now() - last_update).seconds > 3600):
        raw = fetch_flights(mode)
        if raw is not None: cache[mode] = {'data': raw, 'timestamp': datetime.now()}

    flights, total_pax = process_data(cache[mode]['data'], mode)
    weather = get_weather()
    current_time_str = datetime.now(GEG_TZ).strftime("%I:%M %p")

    # Header
    title = "🛫 DEPARTURES" if mode == 'departure' else "🛬 ARRIVALS"
    traf_light = "🟢 BUSY" if total_pax > 500 else "🟡 STEADY" if total_pax > 200 else "🔴 QUIET"
    
    text = f"**{title}** ({TARGET_IATA})\n"
    text += f"📊 Status: {traf_light}\n"
    text += f"⏰ **{current_time_str}**\n"
    text += f"🌡 {weather}\n"
    text += "──────────────────────\n"
    
    if mode == 'arrival':
        text += "_Local Time_ | 🎒 = Curb Ready\n"
    else:
        text += "_Local Time_ | 🛫 = Takeoff\n"

    count = 0
    for f in flights[:10]:
        t_main = f['time'].strftime("%H:%M")
        
        if mode == 'arrival':
            t_ready = f['ready_time'].strftime("%H:%M")
            # Row 1: Icon - Land Time -> Ready Time
            row1 = f"{f['icon']} **{t_main}** ➜ 🎒**{t_ready}**\n"
        else:
            # Row 1: Icon - Takeoff Time - Zone
            row1 = f"{f['icon']} **{t_main}** 🛫 {f['zone'].replace('Zone ','')}\n"
            
        row2 = f"   {f['airline']} ({f['flight']}) ~{f['seats']}p\n"
        text += row1 + row2
        count += 1
        
    if count == 0: text += "💤 No passenger flights found.\n"
        
    text += "──────────────────────\n"
    if last_update:
        age = (datetime.now() - last_update).total_seconds()
        text += f"_Snapshot: {int(age // 60)}m {int(age % 60)}s ago_"

    kb = [
        [InlineKeyboardButton(f"🔄 REFRESH {mode.upper()}", callback_data=f"refresh_{mode}")],
        [InlineKeyboardButton("🔍 Verify on GEG Site", url="https://spokaneairports.net/flight-status")]
    ]
    
    if query:
        await query.message.edit_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

async def refresh_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    mode = query.data.split("_")[1]
    raw = fetch_flights(mode)
    if raw is not None:
        cache[mode] = {'data': raw, 'timestamp': datetime.now()}
        await dashboard(update, context, mode)
    else:
        await query.answer("API Limit/Error.", show_alert=True)

async def dep_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await dashboard(update, context, 'departure')

async def arr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await dashboard(update, context, 'arrival')

if __name__ == '__main__':
    threading.Thread(target=run_web_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', lambda u,c: u.message.reply_text("🚕 **GEG Driver Pro v6.0**\n/arrivals\n/departures")))
    app.add_handler(CommandHandler('departures', dep_command))
    app.add_handler(CommandHandler('arrivals', arr_command))
    app.add_handler(CallbackQueryHandler(refresh_handler))
    print("Bot is running...")
    app.run_polling()
