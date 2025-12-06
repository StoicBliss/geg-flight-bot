import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import aiohttp
import asyncio
from datetime import datetime
from collections import Counter

# -------------------------
# Config
# -------------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")  # Set in Render environment
APP_URL = os.environ.get("APP_URL")  # e.g. "https://gegflightbot.onrender.com"
PORT = int(os.environ.get("PORT", 8443))

# OpenSky API credentials
OPENSKY_USER = os.environ.get("OPENSKY_USER", "")
OPENSKY_PASS = os.environ.get("OPENSKY_PASS", "")

AIRPORT_ICAO = "KGEG"  # Spokane Intl

# -------------------------
# Logging
# -------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# -------------------------
# Helper Functions
# -------------------------
async def fetch_departures():
    """
    Fetch departures from OpenSky Network API
    """
    url = f"https://opensky-network.org/api/flights/departure?airport={AIRPORT_ICAO}&begin={int(datetime.utcnow().timestamp())}&end={int(datetime.utcnow().timestamp()) + 3600*12}"
    auth = aiohttp.BasicAuth(OPENSKY_USER, OPENSKY_PASS)
    
    async with aiohttp.ClientSession(auth=auth) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                logger.warning(f"OpenSky request failed: {resp.status}")
                return []
            data = await resp.json()
            return data

def summarize_by_hour(flights):
    """
    Summarize departures by hour
    """
    hours = []
    for flight in flights:
        if "firstSeen" in flight:
            hour = datetime.utcfromtimestamp(flight["firstSeen"]).hour
            hours.append(hour)
    counter = Counter(hours)
    summary = "\n".join([f"{h}:00 - {counter[h]} departures" for h in sorted(counter)])
    return summary or "No departures found in next 12 hours."

# -------------------------
# Telegram Command Handlers
# -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! I track Spokane Intl Airport departures. Use /departures to see upcoming departures summary by hour."
    )

async def departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("Fetching departures...")
    flights = await fetch_departures()
    summary = summarize_by_hour(flights)
    await msg.edit_text(f"Departures summary (next 12h UTC):\n\n{summary}")

# -------------------------
# Main Function
# -------------------------
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Register commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("departures", departures))

    # Run webhook
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_TOKEN,
        webhook_url=f"{APP_URL}/{TELEGRAM_TOKEN}",
    )

if __name__ == "__main__":
    main()
