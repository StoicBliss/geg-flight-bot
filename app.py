import os
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from collections import Counter

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(level=logging.INFO)

GEG_URL = "https://spokaneairports.net/flight-status/"


# ---------------- SCRAPER ---------------- #

def fetch_departures():
    """Scrape departures from Spokane Airport website."""
    resp = requests.get(GEG_URL, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Find departures table
    departures_table = None
    for table in soup.find_all("table"):
        if "DEPARTURES" in table.text.upper():
            departures_table = table
            break

    if departures_table is None:
        return []

    rows = departures_table.find_all("tr")[1:]  # skip header
    departures = []

    for row in rows:
        cols = [c.get_text(strip=True) for c in row.find_all("td")]
        if len(cols) < 4:
            continue

        flight, airline, destination, sched_time = cols[:4]

        # Parse scheduled time to extract the hour
        try:
            dt = datetime.strptime(sched_time, "%I:%M %p")
            hour = dt.hour
        except:
            continue

        departures.append({
            "flight": flight,
            "airline": airline,
            "destination": destination,
            "time": sched_time,
            "hour": hour,
        })

    return departures


def summarize_by_hour(departures):
    hours = [d["hour"] for d in departures]
    counter = Counter(hours)

    lines = []
    for hr in range(24):
        count = counter.get(hr, 0)
        hr_label = datetime.strptime(str(hr), "%H").strftime("%I %p")
        lines.append(f"{hr_label}: {count} departures")

    return "\n".join(lines)


# ---------------- COMMAND HANDLERS ---------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to GEG Flight Bot!\n"
        "Use /departures to see today's departure activity by hour."
    )


async def departures_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Fetching live flight data… ⏳")

    try:
        departures = fetch_departures()

        if not departures:
            await update.message.reply_text(
                "❌ No departure data available right now. Try again soon."
            )
            return

        summary = summarize_by_hour(departures)
        await update.message.reply_text(
            f"📊 *GEG Departure Activity (Today)*\n\n{summary}",
            parse_mode="Markdown"
        )

    except Exception as e:
        logging.error("Error fetching departures: %s", e)
        await update.message.reply_text("⚠️ Error fetching data — try again later.")


# ---------------- MAIN APP ---------------- #

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN environment variable is missing!")

    app = Application.builder().token(token).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("departures", departures_cmd))

    # NEW for PTB21+
    app.run_polling()


if __name__ == "__main__":
    main()
