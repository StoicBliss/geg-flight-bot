import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import pytz

from telegram import Bot

# ---------- CONFIG ----------
TOKEN = os.getenv("TELEGRAM_TOKEN")  # Set this in Render environment
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Your Render URL
GEG_FLIGHT_STATUS_URL = "https://spokaneairports.net/flight-status/"

bot = Bot(token=TOKEN)
app = Flask(__name__)

# ---------- FUNCTIONS ----------
def fetch_departures():
    response = requests.get(GEG_FLIGHT_STATUS_URL)
    soup = BeautifulSoup(response.content, "html.parser")

    departures = []

    # Scrape the departures table
    table = soup.find("table", {"id": "departures"})
    if not table:
        return departures

    for row in table.find("tbody").find_all("tr"):
        cells = row.find_all("td")
        if len(cells) >= 5:
            time_str = cells[0].text.strip()  # e.g., "12:30 PM"
            airline = cells[1].text.strip()
            flight_num = cells[2].text.strip()
            destination = cells[3].text.strip()
            status = cells[4].text.strip()

            departures.append({
                "time": time_str,
                "airline": airline,
                "flight_num": flight_num,
                "destination": destination,
                "status": status
            })

    return departures

def departures_by_hour(departures):
    hours = defaultdict(int)
    for dep in departures:
        try:
            dt = datetime.strptime(dep["time"], "%I:%M %p")
            hours[dt.hour] += 1
        except:
            continue
    return hours

def busiest_airlines(departures):
    airlines = [dep["airline"] for dep in departures]
    return Counter(airlines).most_common(5)

def forecast_next_day():
    tomorrow = datetime.now(pytz.timezone("US/Pacific")) + timedelta(days=1)
    departures = fetch_departures()
    next_day_departures = []

    for dep in departures:
        try:
            dep_time = datetime.strptime(dep["time"], "%I:%M %p")
            if dep_time.date() == tomorrow.date():
                next_day_departures.append(dep)
        except:
            continue
    return next_day_departures

def busiest_days_of_week():
    departures = fetch_departures()
    days = defaultdict(int)
    tz = pytz.timezone("US/Pacific")
    for dep in departures:
        try:
            dt = datetime.strptime(dep["time"], "%I:%M %p")
            dt = tz.localize(dt)
            day = dt.strftime("%A")
            days[day] += 1
        except:
            continue
    return sorted(days.items(), key=lambda x: x[1], reverse=True)

# ---------- TELEGRAM HANDLERS ----------
@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json()
    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        if text == "/departures":
            deps = fetch_departures()
            hours = departures_by_hour(deps)
            msg = "Departures by hour:\n"
            for h in sorted(hours.keys()):
                msg += f"{h}:00 - {hours[h]} flights\n"
            bot.send_message(chat_id=chat_id, text=msg)

        elif text == "/peakhours":
            deps = fetch_departures()
            hours = departures_by_hour(deps)
            peak_hour = max(hours, key=hours.get)
            bot.send_message(chat_id=chat_id, text=f"Peak departure hour: {peak_hour}:00 with {hours[peak_hour]} flights")

        elif text == "/busiest":
            deps = fetch_departures()
            airlines = busiest_airlines(deps)
            msg = "Busiest airlines today:\n"
            for airline, count in airlines:
                msg += f"{airline} - {count} flights\n"
            bot.send_message(chat_id=chat_id, text=msg)

        elif text == "/forecast":
            next_day = forecast_next_day()
            msg = f"Forecast for tomorrow ({(datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')}):\n"
            msg += f"{len(next_day)} departures scheduled"
            bot.send_message(chat_id=chat_id, text=msg)

        elif text == "/busiestdays":
            days = busiest_days_of_week()
            msg = "Busiest days of the week:\n"
            for day, count in days:
                msg += f"{day}: {count} flights\n"
            bot.send_message(chat_id=chat_id, text=msg)

        else:
            bot.send_message(chat_id=chat_id, text="Send /departures to get departures grouped by hour")

    return "OK"

# ---------- START ----------
if __name__ == "__main__":
    # Set webhook automatically when app starts
    bot.set_webhook(url=f"{WEBHOOK_URL}/webhook/{TOKEN}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
