import os
import requests
from datetime import datetime, timedelta
import pytz
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Environment variables
TOKEN = os.getenv("TOKEN")          # Telegram bot token
CHAT_ID = int(os.getenv("CHAT_ID")) # Your Telegram numeric ID

# Timezone for Spokane
TZ = pytz.timezone("America/Los_Angeles")

# OpenSky departures API
OPENSKY_URL = "https://opensky-network.org/api/flights/departure"

# Store departures count by hour
departures_count = {}

# Scheduler
scheduler = AsyncIOScheduler(timezone=TZ)

# ------------------------------
# Fetch departures from GEG
# ------------------------------
def fetch_departures():
    now = datetime.utcnow()
    begin = int((now - timedelta(hours=12)).timestamp())
    end = int(now.timestamp())

    try:
        response = requests.get(
            OPENSKY_URL, params={"airport": "KGEG", "begin": begin, "end": end}
        )
        if response.status_code == 200:
            flights = response.json()
            count_by_hour = {}
            for flight in flights:
                if flight.get("firstSeen"):
                    dt = (
                        datetime.utcfromtimestamp(flight["firstSeen"])
                        .replace(tzinfo=pytz.utc)
                        .astimezone(TZ)
                    )
                    hour = dt.hour
                    count_by_hour[hour] = count_by_hour.get(hour, 0) + 1

            # Merge into global departures_count
            for hour, count in count_by_hour.items():
                departures_count[hour] = departures_count.get(hour, 0) + count

            print(f"Fetched {len(flights)} departures.")
        else:
            print("Failed to fetch departures, status code:", response.status_code)
    except Exception as e:
        print("Error fetching departures:", e)


# ------------------------------
# Build daily summary message
# ------------------------------
def build_summary():
    if not departures_count:
        return "No departure data collected today."

    message = "🛫 GEG Daily Departure Summary (local time):\n"
    for hour in range(24):
        count = departures_count.get(hour, 0)
        message += f"{hour:02d}:00 - {count} departures\n"

    # Peak hour
    peak_hour = max(departures_count, key=lambda k: departures_count[k])
    message += f"\nPeak Hour: {peak_hour:02d}:00 with {departures_count[peak_hour]} departures."
    return message


# ------------------------------
# Send daily summary at 3:00 AM
# ------------------------------
async def send_daily_summary():
    message = build_summary()
    from telegram import Bot

    bot = Bot(TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text=message)

    # Ask user if they want an immediate schedule update
    await bot.send_message(chat_id=CHAT_ID, text="Do you want a schedule update now? (Yes/No)")

    # Reset departures count for next day
    departures_count.clear()


# ------------------------------
# Telegram command handlers
# ------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to GEG Flight Bot!\n"
        "Commands:\n"
        "/departures - Show recent departures\n"
        "/peak_hours - Show departures by hour\n"
    )


async def departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fetch_departures()
    flights = departures_count.copy()
    if not flights:
        await update.message.reply_text("No departures found.")
        return

    message = "Recent Departures (local time):\n"
    for hour in sorted(flights.keys()):
        message += f"{hour:02d}:00 - {flights[hour]} departures\n"
    await update.message.reply_text(message)


async def peak_hours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fetch_departures()
    flights = departures_count.copy()
    if not flights:
        await update.message.reply_text("No departures found.")
        return

    message = "Departures by Hour:\n"
    for hour in sorted(flights.keys()):
        message += f"{hour:02d}:00 - {flights[hour]} departures\n"
    await update.message.reply_text(message)


# ------------------------------
# Handle Yes/No responses
# ------------------------------
async def handle_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text == "yes":
        fetch_departures()
        message = build_summary()
        await update.message.reply_text("Here is your updated schedule:\n" + message)
    elif text == "no":
        await update.message.reply_text("Okay, no schedule update sent.")


# ------------------------------
# Main
# ------------------------------
if __name__ == "__main__":
    # Telegram bot setup
    app = ApplicationBuilder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("departures", departures))
    app.add_handler(CommandHandler("peak_hours", peak_hours))

    # Responses
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_response))

    # Scheduler jobs
    scheduler.add_job(fetch_departures, "interval", hours=1)  # hourly fetch
    scheduler.add_job(send_daily_summary, "cron", hour=3, minute=0)  # daily summary at 3 AM
    scheduler.start()

    print("Bot started...")
    app.run_polling()
