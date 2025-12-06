from flask import Flask, request
import requests
from bs4 import BeautifulSoup
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler, CallbackContext
from datetime import datetime, timedelta
import pytz
from collections import Counter
from apscheduler.schedulers.background import BackgroundScheduler

# === CONFIG ===
TOKEN = "8377026663:AAFA0PHG4VguKwlyborjSjG2GlUCZ1CznGM"  # replace with your bot token
CHAT_ID = "7486532941"  # Telegram chat ID where bot sends alerts
BOT = Bot(TOKEN)
TIMEZONE = pytz.timezone("America/Los_Angeles")
URL = "https://spokaneairports.net/flight-status/"

app = Flask(__name__)

# === HELPER FUNCTIONS ===

def fetch_departures():
    r = requests.get(URL)
    soup = BeautifulSoup(r.text, "html.parser")
    
    departures = []
    for row in soup.select("table.departures tr"):
        cols = row.find_all("td")
        if len(cols) < 4:
            continue
        flight = cols[0].text.strip()
        airline = cols[1].text.strip()
        time_str = cols[2].text.strip()
        status = cols[3].text.strip()
        try:
            time_obj = datetime.strptime(time_str, "%I:%M %p").time()
        except:
            continue
        departures.append({
            "flight": flight,
            "airline": airline,
            "time": time_obj,
            "status": status
        })
    return departures

def departures_by_hour(departures):
    hour_count = Counter()
    for d in departures:
        hour_count[d["time"].hour] += 1
    return hour_count

def busiest_airlines(departures):
    counter = Counter(d["airline"] for d in departures)
    return counter.most_common(5)

def busiest_days_forecast(departures):
    day_counts = Counter()
    today = datetime.now(TIMEZONE)
    for i in range(7):
        day_counts[(today + timedelta(days=i)).strftime("%A")] = len(departures)
    return day_counts.most_common(3)

# === TELEGRAM COMMANDS ===

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Hi! Use /departures to get departures grouped by hour."
    )

def departures_command(update: Update, context: CallbackContext):
    departures = fetch_departures()
    if not departures:
        update.message.reply_text("No departure data available.")
        return
    
    hour_count = departures_by_hour(departures)
    message = "Departures by hour:\n"
    for hour in sorted(hour_count):
        message += f"{hour:02d}:00 - {hour_count[hour]} flights\n"
    
    peak_hour = max(hour_count, key=hour_count.get)
    message += f"\nPeak departure hour: {peak_hour:02d}:00\n"
    
    airlines = busiest_airlines(departures)
    message += "\nBusiest airlines:\n"
    for a, c in airlines:
        message += f"{a} - {c} flights\n"
    
    forecast = busiest_days_forecast(departures)
    message += "\nForecast busiest days:\n"
    for day, c in forecast:
        message += f"{day} - {c} flights\n"
    
    update.message.reply_text(message)

# === AUTO ALERT FUNCTION ===

def send_peak_alert():
    departures = fetch_departures()
    if not departures:
        BOT.send_message(chat_id=CHAT_ID, text="No departure data available today.")
        return

    hour_count = departures_by_hour(departures)
    peak_hour = max(hour_count, key=hour_count.get)

    message = f"📊 Peak Departure Alert:\nPeak hour today: {peak_hour:02d}:00 with {hour_count[peak_hour]} flights.\nBusiest airlines:\n"
    airlines = busiest_airlines(departures)
    for a, c in airlines:
        message += f"{a} - {c} flights\n"
    
    BOT.send_message(chat_id=CHAT_ID, text=message)

# === FLASK ROUTES ===

@app.route("/webhook/<token>", methods=["POST"])
def webhook(token):
    if token != TOKEN:
        return "Unauthorized", 403
    update = Update.de_json(request.get_json(force=True), BOT)
    dispatcher.process_update(update)
    return "OK"

@app.route("/")
def index():
    return "GEG Flight Bot is running!"

# === TELEGRAM DISPATCHER ===
dispatcher = Dispatcher(BOT, None, workers=0)
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("departures", departures_command))

# === SCHEDULER SETUP ===
scheduler = BackgroundScheduler(timezone=TIMEZONE)
# Send alert every day at 10 AM Spokane time (adjust as needed)
scheduler.add_job(send_peak_alert, "cron", hour=10, minute=0)
scheduler.start()

# === RUN APP ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(__import__("os").environ.get("PORT", 10000)))
