from flask import Flask, request
import requests
from bs4 import BeautifulSoup
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler, CallbackContext
from datetime import datetime, timedelta
import pytz
from collections import Counter, defaultdict

# === CONFIG ===
TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"  # replace with your bot token
BOT = Bot(TOKEN)
TIMEZONE = pytz.timezone("America/Los_Angeles")  # Spokane local time
URL = "https://spokaneairports.net/flight-status/"

app = Flask(__name__)

# === HELPER FUNCTIONS ===

def fetch_departures():
    """Scrape Spokane Airport departures page for flights."""
    r = requests.get(URL)
    soup = BeautifulSoup(r.text, "html.parser")
    
    departures = []
    
    # Simplified parsing logic: adapt as needed based on page structure
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
    """Group departures by hour."""
    hour_count = Counter()
    for d in departures:
        hour = d["time"].hour
        hour_count[hour] += 1
    return hour_count

def busiest_airlines(departures):
    """Count flights per airline."""
    counter = Counter(d["airline"] for d in departures)
    return counter.most_common(5)

def busiest_days_forecast(departures):
    """Simulate busiest days of week for forecast (placeholder)."""
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
    
    # By hour
    hour_count = departures_by_hour(departures)
    message = "Departures by hour:\n"
    for hour in sorted(hour_count):
        message += f"{hour:02d}:00 - {hour_count[hour]} flights\n"
    
    # Peak hour
    peak_hour = max(hour_count, key=hour_count.get)
    message += f"\nPeak departure hour: {peak_hour:02d}:00\n"
    
    # Busiest airlines
    airlines = busiest_airlines(departures)
    message += "\nBusiest airlines:\n"
    for a, c in airlines:
        message += f"{a} - {c} flights\n"
    
    # Forecast next days
    forecast = busiest_days_forecast(departures)
    message += "\nForecast busiest days:\n"
    for day, c in forecast:
        message += f"{day} - {c} flights\n"
    
    update.message.reply_text(message)

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
from telegram.ext import Dispatcher
dispatcher = Dispatcher(BOT, None, workers=0)
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("departures", departures_command))

# === RUN APP ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(__import__("os").environ.get("PORT", 10000)))
