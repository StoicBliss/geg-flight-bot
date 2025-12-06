import os
import time
import requests
import pandas as pd
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Read credentials from environment variables
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENSKY_USERNAME = os.environ.get("OPENSKY_USERNAME")
OPENSKY_PASSWORD = os.environ.get("OPENSKY_PASSWORD")

# Check if credentials exist
if not all([TELEGRAM_TOKEN, OPENSKY_USERNAME, OPENSKY_PASSWORD]):
    raise ValueError("Please set TELEGRAM_TOKEN, OPENSKY_USERNAME, and OPENSKY_PASSWORD as environment variables.")

# --------- Functions to Fetch & Process Flight Data ---------
def get_departures():
    """Fetch departures from GEG airport in the last 24 hours."""
    end_time = int(time.time())
    begin_time = end_time - 24*3600  # last 24 hours
    
    url = f"https://opensky-network.org/api/flights/departure?airport=GEG&begin={begin_time}&end={end_time}"
    try:
        response = requests.get(url, auth=(OPENSKY_USERNAME, OPENSKY_PASSWORD))
        response.raise_for_status()
    except Exception as e:
        print("Error fetching data from OpenSky:", e)
        return pd.DataFrame()
    
    data = response.json()
    if not data:
        return pd.DataFrame()
    
    df = pd.DataFrame(data)
    # Convert departure time to local hour
    df['hour'] = pd.to_datetime(df['firstSeen'], unit='s').dt.hour
    return df

def departures_by_hour(df):
    """Summarize departures by hour."""
    if df.empty:
        return "No departure data available."
    
    summary = df.groupby('hour').size().sort_index()
    message = "🚀 Departures by Hour (last 24h at GEG):\n"
    for hour, count in summary.items():
        message += f"{hour}:00 - {count} departures\n"
    return message

# --------- Telegram Bot Handlers ---------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! I'm your GEG Flight Tracker bot.\n"
        "Use /departures to see flight peaks in the last 24 hours."
    )

async def departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = get_departures()
    message = departures_by_hour(df)
    await update.message.reply_text(message)

# --------- Run Bot ---------
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("departures", departures))
    
    print("🚀 GEGFlightBot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
