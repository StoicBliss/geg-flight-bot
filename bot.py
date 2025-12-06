import requests
from datetime import datetime, timedelta
import pytz
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = "YOUR_BOT_TOKEN"
TZ = pytz.timezone('America/Los_Angeles')
OPENSKY_URL = "https://opensky-network.org/api/flights/departure"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to GEG Flight Bot!\nCommands:\n/departures\n/peak_hours"
    )

async def departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    flights = fetch_departures()
    if not flights:
        await update.message.reply_text("No departures found.")
        return

    message = "Recent Departures (local time):\n"
    for flight in flights[:10]:
        callsign = flight.get('callsign', 'N/A')
        dt = datetime.utcfromtimestamp(flight['firstSeen']).replace(tzinfo=pytz.utc).astimezone(TZ)
        message += f"{dt.strftime('%H:%M')} - {callsign}\n"

    await update.message.reply_text(message)

async def peak_hours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    flights = fetch_departures()
    if not flights:
        await update.message.reply_text("No departures found.")
        return

    hours = departures_by_hour(flights)
    message = "Departures by Hour:\n"
    for hour, count in hours.items():
        message += f"{hour:02d}:00 - {count} departures\n"
    await update.message.reply_text(message)

def fetch_departures():
    now = datetime.utcnow()
    begin = int((now - timedelta(hours=12)).timestamp())
    end = int(now.timestamp())

    try:
        response = requests.get(OPENSKY_URL, params={'airport': 'KGEG', 'begin': begin, 'end': end})
        if response.status_code == 200:
            return response.json()
        else:
            return []
    except:
        return []

def departures_by_hour(flights):
    hours = {}
    for flight in flights:
        if flight.get('firstSeen'):
            dt = datetime.utcfromtimestamp(flight['firstSeen']).replace(tzinfo=pytz.utc).astimezone(TZ)
            hour = dt.hour
            hours[hour] = hours.get(hour, 0) + 1
    return dict(sorted(hours.items()))

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("departures", departures))
    app.add_handler(CommandHandler("peak_hours", peak_hours))

    app.run_polling()
