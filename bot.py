import os
import requests
from datetime import datetime, timedelta
from telegram.ext import ApplicationBuilder, CommandHandler

OPENSKY_USER = os.getenv("OPENSKY_USER")
OPENSKY_PASS = os.getenv("OPENSKY_PASS")
BOT_TOKEN = os.getenv("BOT_TOKEN")

GEG = "GEG"


def get_departures():
    try:
        now = int(datetime.utcnow().timestamp())
        one_hour_later = int((datetime.utcnow() + timedelta(hours=6)).timestamp())

        url = f"https://opensky-network.org/api/flights/departure?airport={GEG}&begin={now}&end={one_hour_later}"

        r = requests.get(url, auth=(OPENSKY_USER, OPENSKY_PASS))
        data = r.json()

        if not data or "error" in data:
            return "No data or API error. Try again later."

        hourly = {}

        for flight in data:
            ts = flight.get("firstSeen")
            if not ts:
                continue
            hour = datetime.utcfromtimestamp(ts).strftime("%H:00")
            hourly[hour] = hourly.get(hour, 0) + 1

        if not hourly:
            return "No departures found in the selected window."

        result = "GEG Departures by Hour (Next Few Hours)\n\n"
        for h, c in sorted(hourly.items()):
            result += f"{h} UTC  {c} flights\n"

        return result

    except Exception as e:
        return f"Error fetching data: {e}"


async def departures(update, context):
    report = get_departures()
    await update.message.reply_text(report)


async def start(update, context):
    await update.message.reply_text("Welcome. Use /departures to check departure activity.")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("departures", departures))

    app.run_polling()


if __name__ == "__main__":
    main()
