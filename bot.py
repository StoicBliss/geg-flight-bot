import requests
from datetime import datetime, timedelta
import pytz
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# Telegram token
TOKEN = "YOUR_BOT_TOKEN"

# Spokane timezone
TZ = pytz.timezone('America/Los_Angeles')

# OpenSky API base URL
OPENSKY_URL = "https://opensky-network.org/api/flights/departure"

# Function to fetch departures
def fetch_departures():
    """
    Fetch departures from Spokane International (KGEG) for the last 12 hours.
    """
    now = datetime.utcnow()
    begin = int((now - timedelta(hours=12)).timestamp())
    end = int(now.timestamp())

    params = {
        'airport': 'KGEG',
        'begin': begin,
        'end': end
    }

    try:
        response = requests.get(OPENSKY_URL, params=params)
        if response.status_code == 200:
            return response.json()
        else:
            return []
    except Exception as e:
        print("Error fetching departures:", e)
        return []

# Group departures by hour
def departures_by_hour(departures):
    """
    Returns a dict: hour -> number of departures
    """
    hours = {}
    for flight in departures:
        if flight.get('firstSeen'):
            dt = datetime.utcfromtimestamp(flight['firstSeen']).replace(tzinfo=pytz.utc).astimezone(TZ)
            hour = dt.hour
            hours[hour] = hours.get(hour, 0) + 1
    return dict(sorted(hours.items()))

# Telegram handlers
def start(update: Update, context: CallbackContext):
    update.message.reply_text("Welcome to GEG Flight Bot!\nCommands:\n/departures - show recent departures\n/peak_hours - show busiest hours")

def departures(update: Update, context: CallbackContext):
    flights = fetch_departures()
    if not flights:
        update.message.reply_text("No departures found.")
        return

    message = "Recent Departures (local time):\n"
    for flight in flights[:10]:  # show top 10
        callsign = flight.get('callsign', 'N/A')
        dt = datetime.utcfromtimestamp(flight['firstSeen']).replace(tzinfo=pytz.utc).astimezone(TZ)
        message += f"{dt.strftime('%H:%M')} - {callsign}\n"

    update.message.reply_text(message)

def peak_hours(update: Update, context: CallbackContext):
    flights = fetch_departures()
    if not flights:
        update.message.reply_text("No departures found.")
        return

    hours = departures_by_hour(flights)
    message = "Departures by Hour:\n"
    for hour, count in hours.items():
        message += f"{hour:02d}:00 - {count} departures\n"
    update.message.reply_text(message)

# Main function
def main():
    updater = Updater(TOKEN)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("departures", departures))
    dp.add_handler(CommandHandler("peak_hours", peak_hours))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
