import os
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from collections import Counter
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

GEG_URL = "https://spokaneairports.net/flight-status/"

# ---------------- SCRAPER ---------------- #

def fetch_departures():
    """Scrape departures from Spokane Airport website."""
    response = requests.get(GEG_URL, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Page contains two tables: Arrivals and Departures.
    # We find the departures table by looking for header text.
    departures_table = None
    for table in soup.find_all("table"):
        if "DEPARTURES" in table.text.upper():
            departures_table = table
            break

    if departures_table is None:
        return []

    rows = departures_table.find_all("tr")[1:]  # skip header row

    departures = []
    for row in rows:
        cols = [c.get_text(strip=True) for c in row.find_all("td")]
        if len(cols) < 4:
            continue

        flight, airline, destination, sched_time = cols[:4]

        # Attempt to parse time (e.g. "6:05 AM")
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
            "hour": hour
        })

    return departures

# ---------------- UTILITIES ---------------- #

def summarize_by_hour(departures):
    hours = [d["hour"] for d in departures]
    counter = Counter(hours)

    # Format summary
    lines = []
    for hr in range(24):
        count = counter.get(hr, 0)
        label = datetime.strptime(str(hr), "%H").strftime("%I %p")
        lines.append(f"{label}: {count} departures")

    return "\n".join(lines)


# ---------------- BOT HANDLERS ---------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome! Send /departures to view today's GEG departure peak hours."
    )

async def departures_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Fetching live departure data… please wait ⏳")

    try:
        departures = fetch_departures()
        if not departures:
            await update.message.reply_text("No departure data found. Try again soon.")
            return

        summary = summarize_by_hour(departures)
        await update.message.reply_text(
            "📊 **GEG Departure Peak Hours (Today)**\n\n" + summary,
            parse_mode="Markdown"
        )

    except Exception as e:
        logging.error(e)
        await update.message.reply_text("Error fetching data. Try again later.")


# ---------------- MAIN ---------------- #

if __name__ == "__main__":
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable is required.")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("departures", departures_cmd))

    app.run_polling()
