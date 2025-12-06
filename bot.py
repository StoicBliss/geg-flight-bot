import os
import requests
import datetime
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

OPENSKY_USER = os.getenv("OPENSKY_USER")
OPENSKY_PASS = os.getenv("OPENSKY_PASS")

GEG = "GEG"
SPOKANE_TZ = ZoneInfo("America/Los_Angeles")

def fetch_departures():
    now = int(datetime.datetime.utcnow().timestamp())
    six_hours = now + 6 * 3600

    url = f"https://opensky-network.org/api/flights/departure?airport={GEG}&begin={now}&end={six_hours}"
    response = requests.get(url, auth=(OPENSKY_USER, OPENSKY_PASS))

    if response.status_code != 200:
        return None

    return response.json()

def group_by_hour(departures):
    hourly = {}

    for flight in departures:
        dep_time = flight.get("lastSeen") or flight.get("firstSeen")
        if not dep_time:
            continue

        dt = datetime.datetime.fromtimestamp(dep_time, SPOKANE_TZ)
        hr = dt.replace(minute=0, second=0, microsecond=0)

        hr_str = hr.strftime("%H:00")
        hourly[hr_str] = hourly.get(hr_str, 0) + 1

    return hourly

async def departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    flights = fetch_departures()

    if not flights:
        await update.message.reply_text("Could not get departure data right now.")
        return

    grouped = group_by_hour(flights)

    if not grouped:
        await update.message.reply_text("No upcoming departures found in the next hours.")
        return

    sorted_hours = sorted(grouped.items())

    text = "Upcoming departures from GEG:\n\n"
    for hour, count in sorted_hours:
        text += f"{hour} - {count} flights\n"

    peak = max(grouped, key=grouped.get)
    text += f"\nPeak hour: {peak}"

    await update.message.reply_text(text)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome. Use /departures to see upcoming flight activity at GEG.")

def main():
    token = os.getenv("BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("departures", departures))

    app.run_polling()

if __name__ == "__main__":
    main()
