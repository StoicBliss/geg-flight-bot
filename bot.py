import os
import time
import requests
import pandas as pd
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --------- Environment Variables ---------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENSKY_USERNAME = os.environ.get("OPENSKY_USERNAME")
OPENSKY_PASSWORD = os.environ.get("OPENSKY_PASSWORD")
PORT = int(os.environ.get("PORT", 8000))  # Render assigns this automatically
APP_URL = "https://gegflightbot.onrender.com"  # Your Render app URL

if not all([TELEGRAM_TOKEN, OPENSKY_USERNAME, OPENSKY_PASSWORD, APP_URL]):
    raise ValueError("Set TELEGRAM_TOKEN, OPENSKY_USERNAME, OPENSKY_PASSWORD, and APP_URL.")

# --------- Flight Data Functions ---------
def get_departures(hours_back=24):
    """Fetch departures from GEG in the past X hours."""
    end_time = int(time.time())
    begin_time = end_time - hours_back * 3600
    url = f"https://opensky-network.org/api/flights/departure?airport=GEG&begin={begin_time}&end={end_time}"
    try:
        response = requests.get(url, auth=(OPENSKY_USERNAME, OPENSKY_PASSWORD))
        response.raise_for_status()
    except Exception as e:
        print("Error fetching departures:", e)
        return pd.DataFrame()
    
    data = response.json()
    if not data:
        return pd.DataFrame()
    
    df = pd.DataFrame(data)
    df['hour'] = pd.to_datetime(df['firstSeen'], unit='s').dt.hour
    return df

def get_upcoming_departures(hours_ahead=12):
    """Fetch upcoming departures from GEG for next X hours."""
    now = int(time.time())
    future = now + hours_ahead * 3600
    url = f"https://opensky-network.org/api/flights/departure?airport=GEG&begin={now}&end={future}"
    try:
        response = requests.get(url, auth=(OPENSKY_USERNAME, OPENSKY_PASSWORD))
        response.raise_for_status()
    except Exception as e:
        print("Error fetching upcoming departures:", e)
        return pd.DataFrame()
    
    data = response.json()
    if not data:
        return pd.DataFrame()
    
    df = pd.DataFrame(data)
    df['hour'] = pd.to_datetime(df['firstSeen'], unit='s').dt.hour
    return df

def departures_by_hour(df):
    if df.empty:
        return "No data available."
    summary = df.groupby('hour').size().sort_index()
    message = ""
    for hour, count in summary.items():
        message += f"{hour}:00 - {count} departures\n"
    return message

def predict_peak_hours(days=7):
    now = int(time.time())
    begin = now - days * 24 * 3600
    end = now
    url = f"https://opensky-network.org/api/flights/departure?airport=GEG&begin={begin}&end={end}"
    try:
        response = requests.get(url, auth=(OPENSKY_USERNAME, OPENSKY_PASSWORD))
        response.raise_for_status()
    except Exception as e:
        print("Error fetching historical data:", e)
        return pd.Series()
    
    data = response.json()
    if not data:
        return pd.Series()
    
    df = pd.DataFrame(data)
    df['hour'] = pd.to_datetime(df['firstSeen'], unit='s').dt.hour
    summary = df.groupby('hour').size() / days
    summary = summary.sort_index()
    return summary

def format_prediction(summary):
    if summary.empty:
        return "No historical data available for prediction."
    message = "📊 Predicted Peak Hours (Average Departures per Hour):\n"
    for hour, count in summary.items():
        message += f"{hour}:00 - {count:.1f} departures\n"
    return message

# --------- Telegram Handlers ---------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! I'm your GEG Flight Tracker bot.\n"
        "Commands:\n"
        "/departures - Last 24h departures\n"
        "/upcoming - Next 12h departures\n"
        "/predict - Predicted peak hours"
    )

async def departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = get_departures()
    message = "📅 Departures in the last 24 hours at GEG:\n" + departures_by_hour(df)
    await update.message.reply_text(message)

async def upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = get_upcoming_departures()
    message = "📅 Upcoming departures (next 12 hours at GEG):\n" + departures_by_hour(df)
    await update.message.reply_text(message)

async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    summary = predict_peak_hours()
    message = format_prediction(summary)
    await update.message.reply_text(message)

# --------- Main Bot (Webhook Mode) ---------
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("departures", departures))
    app.add_handler(CommandHandler("upcoming", upcoming))
    app.add_handler(CommandHandler("predict", predict))
    
    print(f"🚀 GEGFlightBot started on webhook {APP_URL}/{TELEGRAM_TOKEN}")
    
    # Run webhook (PTB will handle HTTPS automatically)
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_TOKEN
    )

if __name__ == "__main__":
    main()
