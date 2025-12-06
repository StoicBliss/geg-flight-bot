import logging
from datetime import datetime, timezone
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ---------------- CONFIG ---------------- #
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
AIRPORT_ICAO = "YOUR_AIRPORT_ICAO"

# OpenSky credentials
OPENSKY_USERNAME = "YOUR_OPENSKY_USERNAME"
OPENSKY_PASSWORD = "YOUR_OPENSKY_PASSWORD"

# ---------------- LOGGING ---------------- #
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------- COMMANDS ---------------- #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I'm your flight bot. Use /departures to get upcoming flights.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/departures - Get upcoming flights from the airport")

async def departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Time window: now to 12 hours ahead
    now_ts = int(datetime.now(timezone.utc).timestamp())
    end_ts = now_ts + 3600 * 12
    url = f"https://opensky-network.org/api/flights/departure?airport={AIRPORT_ICAO}&begin={now_ts}&end={end_ts}"

    try:
        response = requests.get(url, auth=(OPENSKY_USERNAME, OPENSKY_PASSWORD))
        if response.status_code == 200:
            flights = response.json()
            if not flights:
                await update.message.reply_text("No upcoming departures found.")
                return

            message = "Upcoming departures:\n"
            for f in flights[:10]:  # limit to 10 flights to avoid long messages
                callsign = f.get("callsign", "N/A").strip()
                est_departure = datetime.fromtimestamp(f.get("firstSeen", now_ts), tz=timezone.utc)
                message += f"{callsign} at {est_departure.strftime('%Y-%m-%d %H:%M UTC')}\n"

            await update.message.reply_text(message)
        else:
            logger.warning(f"OpenSky request failed: {response.status_code}")
            await update.message.reply_text("Failed to fetch flight data. Please try again later.")
    except Exception as e:
        logger.error(f"Error fetching departures: {e}")
        await update.message.reply_text("An error occurred while fetching flight data.")

# ---------------- MAIN ---------------- #
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Register commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("departures", departures))

    # Start bot
    logger.info("Starting bot...")
    app.run_polling()
