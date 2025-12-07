import logging
import os
import requests
import threading
import time
import html  # <--- Added for proper HTML sanitization
from flask import Flask 
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler
from telegram.error import BadRequest

# --- WEB SERVER (KEEPS BOT ALIVE) --- #
app = Flask(__name__)

@app.route('/')
def health_check():
    return "GEG Pro Bot (Final Stable) Online!"

def run_web_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- CONFIGURATION --- #
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AIRLABS_API_KEY = os.getenv("AIRLABS_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

AIRPORT_IATA = 'GEG'
TIMEZONE = pytz.timezone('America/Los_Angeles')

# --- DATA MAPS --- #
AIRLINE_NAMES = {
    'AA': 'American', 'AS': 'Alaska', 'DL': 'Delta', 'UA': 'United',
    'WN': 'Southwest', 'F9': 'Frontier', 'G4': 'Allegiant', 'SY': 'Sun Country',
    'NK': 'Spirit', 'B6': 'JetBlue', 'HA': 'Hawaiian', 'QX': 'Horizon',
    'OO': 'SkyWest', 'MQ': 'Envoy', 'YX': 'Republic', 'YV': 'Mesa',
    '9E': 'Endeavor', 'OH': 'PSA', 'TN': 'Air Tahiti Nui', 'VS': 'Virgin Atlantic',
    'BA': 'British Airways', 'JL': 'Japan Airlines', 'QF': 'Qantas',
    'KE': 'Korean Air', 'LH': 'Lufthansa', 'FI': 'Icelandair',
    'AF': 'Air France', 'KL': 'KLM', 'QR': 'Qatar Airways', 'WS': 'WestJet'
}

TERMINAL_MAP = {
    'DL': 'Zone A/B (Rotunda)', 'UA': 'Zone A/B (Rotunda)',
    'WN': 'Zone A/B (Rotunda)', 'SY': 'Zone A/B (Rotunda)',
    'G4': 'Zone A/B (Rotunda)', 'NK': 'Zone A/B (Rotunda)',
    'OO': 'Zone A/B (Check Screen)', 
    'AS': 'Zone C (North)', 'QX': 'Zone C (North)',
    'AA': 'Zone C (North)', 'F9': 'Zone C (North)',
    'HA': 'Zone C (North)', 'TN': 'Zone C (North)',
    'BA': 'Zone C (North)', 'JL': 'Zone C (North)'
}

# --- GLOBAL CACHE --- #
flight_cache = {
    "arrival": {"data": None, "timestamp": 0},
    "departure": {"data": None, "timestamp": 0}
}
CACHE_DURATION = 900 

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- HELPER FUNCTIONS --- #
def get_spokane_time():
    return datetime.now(TIMEZONE)

def get_weather():
    url = f"http://api.openweathermap.org/data/2.5/weather?lat=47.619&lon=-117.535&appid={WEATHER_API_KEY}&units=imperial"
    try:
        r = requests.get(url, timeout=5).json()
        if r.get('cod') != 200: return None, "Unavailable"
        temp = round(r['main']['temp'])
        desc = r['weather'][0]['description'].title()
        return temp, desc
    except:
        return None, "Unavailable"

def fetch_flights(mode):
    global flight_cache
    current_time = time.time()
    
    if flight_cache[mode]["data"] and (current_time - flight_cache[mode]["timestamp"] < CACHE_DURATION):
        return flight_cache[mode]["data"]

    logger.info(f"Fetching {mode} from AirLabs...")
    base_url = "https://airlabs.co/api/v9/schedules"
    
    params = {
        'api_key': AIRLABS_API_KEY,
        'arr_iata' if mode == 'arrival' else 'dep_iata': AIRPORT_IATA
        # LIMIT REMOVED: Fetches max available for the day
    }

    try:
        r = requests.get(base_url, params=params, timeout=15)
        data = r.json()
        
        raw_flights = data.get('response', [])
        processed_flights = []
        now = get_spokane_time()
        seen_flights = set()

        for f in raw_flights:
            try:
                code = f.get('airline_iata')
                num = f.get('flight_number')
                
                if not code or not num: continue

                # --- FILTERS ---
                # 1. Skip Codeshares (Marketing duplicates)
                if f.get('cs_flight_number'): continue
                
                # 2. Skip Exact Duplicates
                uid = f"{code}{num}"
                if uid in seen_flights: continue
                seen_flights.add(uid)

                # 3. Skip Cargo
                if code in ['FX', '5X', 'PO', 'K4', 'QY', 'ABX', 'ATI']: continue 

                # --- TIMING ---
                sched_str = f.get('arr_time') if mode == 'arrival' else f.get('dep_time')
                est_str = f.get('arr_estimated') if mode == 'arrival' else f.get('dep_estimated')
                
                if not sched_str: continue
                
                final_str = est_str if est_str else sched_str
                
                sched_dt = datetime.strptime(sched_str, '%Y-%m-%d %H:%M')
                sched_local = TIMEZONE.localize(sched_dt)
                
                final_dt = datetime.strptime(final_str, '%Y-%m-%d %H:%M')
                final_local = TIMEZONE.localize(final_dt)

                if final_local < now - timedelta(minutes=20): continue
                if final_local > now + timedelta(hours=24): continue

                delay_mins = int((final_local - sched_local).total_seconds() / 60)
                
                # --- STATUS ---
                api_status = f.get('status', '').lower()
                status_display = ""
                
                if api_status == 'cancelled':
                    status_display = "🔴 CANCELLED"
                elif delay_mins > 15:
                    status_display = f"⚠️ Delayed {delay_mins}m"
                
                # --- ZONE ---
                api_term = f.get('arr_terminal') if mode == 'arrival' else f.get('dep_terminal')
                zone = "Check Screen"
                if api_term:
                    if 'C' in str(api_term): zone = "Zone C (North)"
                    elif 'A' in str(api_term) or 'B' in str(api_term): zone = "Zone A/B (Rotunda)"
                else:
                    zone = TERMINAL_MAP.get(code, "Zone A/B")

                processed_flights.append({
                    'airline': AIRLINE_NAMES.get(code, code),
                    'code': code,
                    'num': num,
                    'time': final_local,
                    'time_str': final_local.strftime('%H:%M'),
                    'zone': zone,
                    'status': status_display, 
                    'is_problem': (api_status == 'cancelled' or delay_mins > 15)
                })
            except Exception:
                continue

        processed_flights.sort(key=lambda x: x['time'])
        flight_cache[mode]["data"] = processed_flights
        flight_cache[mode]["timestamp"] = current_time
        return processed_flights

    except Exception as e:
        logger.error(f"API Error: {e}")
        return []

async def safe_edit(context, chat_id, msg_id, text, reply_markup=None):
    try:
        if len(text) > 4000: text = text[:4000] + "\n... (truncated)"
        await context.bot.edit_message_text(
            chat_id=chat_id, 
            message_id=msg_id, 
            text=text, 
            parse_mode='HTML', 
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
    except BadRequest:
        pass 
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML', reply_markup=reply_markup)

# --- BOT COMMANDS --- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚘 <b>GEG Pro Driver Bot</b>\n/status, /arrivals, /departures, /delays", parse_mode='HTML')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("📡 Analyzing...")
    try:
        temp, weather = get_weather()
        flights = fetch_flights('arrival')
        now = get_spokane_time()
        
        active_flights = [f for f in flights if "CANCELLED" not in f['status']]
        count = len([f for f in active_flights if now < f['time'] < now + timedelta(hours=1)])
        
        strategy = "⚪ Stay Downtown"
        if count >= 2: strategy = "🟡 Head to Cell Phone Lot"
        if count >= 4: strategy = "🟢 GO TO AIRPORT NOW"
        if weather and ("Rain" in weather or "Snow" in weather): strategy += " (Surge Likely)"
        
        text = (f"📊 <b>STATUS: {now.strftime('%I:%M %p')}</b>\n"
                f"🌡️ {temp}°F, {weather}\n"
                f"🛬 Inbound (1hr): {count} planes\n"
                f"🚦 {strategy}")

        # Corrected Google Maps Link for precise navigation
        map_url = "https://www.google.com/maps/search/?api=1&query=Spokane+International+Airport+Cell+Phone+Waiting+Lot"
        keyboard = [[InlineKeyboardButton("🗺️ Nav to Waiting Lot", url=map_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit(context, update.effective_chat.id, msg.message_id, text, reply_markup)
    except Exception as e:
        await safe_edit(context, update.effective_chat.id, msg.message_id, f"Error: {e}")

async def show_arrivals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("📡 Fetching Arrivals...")
    flights = fetch_flights('arrival')
    
    if not flights:
        await safe_edit(context, update.effective_chat.id, msg.message_id, "No upcoming arrivals.")
        return

    text = "🛬 <b>ARRIVALS</b>\nTime | Airline | Flight | Pickup | Zone\n"
    text += "-----------------------------------------\n"
    
    for f in flights[:15]:
        pickup = (f['time'] + timedelta(minutes=20)).strftime('%H:%M')
        status_icon = "⚠️ " if "Delayed" in f['status'] else ("🔴 " if "CANCELLED" in f['status'] else "")
        
        # Proper HTML Escaping
        airline_safe = html.escape(f['airline'])
        
        line = f"{status_icon}{f['time_str']} | {airline_safe} | {f['code']}{f['num']} | {pickup} | {f['zone']}\n"
        text += line
    
    await safe_edit(context, update.effective_chat.id, msg.message_id, text)

async def show_departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("📡 Fetching Departures...")
    flights = fetch_flights('departure')
    
    if not flights:
        await safe_edit(context, update.effective_chat.id, msg.message_id, "No upcoming departures.")
        return

    text = "🛫 <b>DEPARTURES</b>\nTime | Airline | Flight | Zone\n"
    text += "-----------------------------------------\n"
    
    for f in flights[:15]:
        status_icon = "⚠️ " if "Delayed" in f['status'] else ("🔴 " if "CANCELLED" in f['status'] else "")
        airline_safe = html.escape(f['airline'])
        
        line = f"{status_icon}{f['time_str']} | {airline_safe} | {f['code']}{f['num']} | {f['zone']}\n"
        text += line
    
    await safe_edit(context, update.effective_chat.id, msg.message_id, text)

async def show_delays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("📡 Scanning for Issues...")
    arr = fetch_flights('arrival')
    dep = fetch_flights('departure')
    
    problems = []
    # Use .copy() to prevent cache mutation bugs
    for f in arr:
        if f['is_problem']: 
            p = f.copy()
            p['type'] = "🛬 Arr"
            problems.append(p)
    for f in dep:
        if f['is_problem']: 
            p = f.copy()
            p['type'] = "🛫 Dep"
            problems.append(p)
            
    problems.sort(key=lambda x: x['time'])
    
    if not problems:
        await safe_edit(context, update.effective_chat.id, msg.message_id, "✅ All systems normal. No major delays found.")
        return

    text = "🚨 <b>TROUBLE MONITOR (Delays/Cancels)</b>\n"
    text += "-----------------------------------------\n"
    
    for f in problems[:20]:
        status_safe = html.escape(f['status'])
        line = f"{f['time_str']} | {f['type']} | {f['code']}{f['num']} | <b>{status_safe}</b>\n"
        text += line
        
    await safe_edit(context, update.effective_chat.id, msg.message_id, text)

if __name__ == '__main__':
    threading.Thread(target=run_web_server).start()
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('status', status))
    application.add_handler(CommandHandler('arrivals', show_arrivals))
    application.add_handler(CommandHandler('departures', show_departures))
    application.add_handler(CommandHandler('delays', show_delays))
    
    application.run_polling()
