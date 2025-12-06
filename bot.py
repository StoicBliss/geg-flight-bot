import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ------------------ Configuration ------------------

# Fetch credentials from environment variables
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENSKY_USERNAME = os.environ.get("OPENSKY_USERNAME")
OPENSKY_PASSWORD = os.environ.get("OPENSKY_PASSWORD")
AIRPORT_ICAO = os.environ.get("AIRPORT_ICAO", "KJFK")  # default example

# Validate critical variables
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN environment variable is not set!")
if not OPENSKY_USERNAME or not OPENSKY_PASSWORD:
    raise ValueError("OpenSky credentials are not set!")
if not AIRPORT_ICAO:
    raise ValueError("AIRPORT_ICAO environment variable is not set!")

# ------------------ Logging ------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# ------------------ Command Handlers ------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! Flight bot is online ✈️")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start - Start the bot\n/help - Show this message")

# ------------------ Main ------------------
def main():
    # Build the bot application
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Register command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    # Start the bot with polling
    app.run_polling()

if __name__ == "__main__":
    main()
