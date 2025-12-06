import os
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from collections import Counter

from telegram import Update, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    AIORateLimiter,
    JobQueue,
)

from chart import create_departure_chart

logging.basicConfig(level=logging.INFO)

GEG_URL = "https://spokaneairports.net/flight-status/"

# Caching to reduce scraping frequency
last_scrape = {
    "timestamp": None,
    "data": None
}


# ---------------- SCRAPER ---------------- #

def fetch_departures(force=False):
    """Scrape departures with 5-minute caching."""
    from time import time

    if not force and last_scrape["timestamp"] and time() - last_scrape["timestamp"] < 300:
        return last_scrape["data"]

    resp = requests.get(GEG_URL, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    departures_table = None
    for table in soup.find_all("table"):
        if "DEPARTURES" in table.text.upper():
            departures_table = table
            break

    if not departures_table:
        return []

    rows = departures_table.find_all("tr")[1:]
    departures = []

    for row in rows:
        cols = [c.get_text(strip=True) for c in row.find_all("td")]
        if len(cols) < 4:
            continue

        flight, airline, destination, sched_time = cols[:4]

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

    last_scrape["timestamp"] = time()
    last_scrape["data"] = departures
    return departures


def summarize_by_hour(departures):
    hours = [d["hour"] for d in departures]
    return Counter(hours)


# ---------------- COMMAND HANDLERS ---------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to GEG Flight Bot!\n\n"
        "Commands:\n"
        "/departures — Get summary + chart\n"
        "/alerts_on — Start spike alerts\n"
        "/alerts_off — Stop alerts\n"
    )


async def departures_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Fetching live data…")

    deps = fetch_departures(force=True)
    counter = summarize_by_hour(deps)

    # Text summary
    lines = []
    for h in range(24):
        label = datetime.strptime(str(h), "%H").strftime("%I %p")
        lines.append(f"{label}: {counter.get(h, 0)} departures")

    await update.message.reply_text("📊 *GEG Departure Activity*\n\n" + "\n".join(lines), parse_mode="Markdown")

    # Chart
    chart_path = create_departure_chart(counter)
    await update.message.reply_photo(InputFile(chart_path))


# ---------------- ALERT SYSTEM ---------------- #

async def alert_check(context: ContextTypes.DEFAULT_TYPE):
    """Checks for high-volume departure hours."""
    chat_id = context.job.chat_id

    deps = fetch_departures()
    counter = summarize_by_hour(deps)

    # Alert condition: any hour with >= 5 departures
    spikes = [h for h, count in counter.items() if count >= 5]

    if spikes:
        msg = "⚠️ *Upcoming High Departure Volume Detected!*\n\n"
        for h in spikes:
            label = datetime.strptime(str(h), "%H").strftime("%I %p")
            msg += f"{label}: {counter[h]} departures\n"

        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")


async def alerts_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    job_removed = remove_job_if_exists(str(update.effective_chat.id), context)

    context.job_queue.run_repeating(
        alert_check,
        interval=3600,  # check once per hour
        first=10,
        chat_id=update.effective_chat.id,
        name=str(update.effective_chat.id),
    )

    await update.message.reply_text("🔔 Alerts enabled! You will be notified hourly when peak departures occur.")


async def alerts_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    removed = remove_job_if_exists(str(update.effective_chat.id), context)
    if removed:
        await update.message.reply_text("🔕 Alerts disabled.")
    else:
        await update.message.reply_text("No alerts were active.")


def remove_job_if_exists(name: str, context: ContextTypes.DEFAULT_TYPE):
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True


# ---------------- MAIN ---------------- #

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN missing!")

    app = Application.builder().token(token).rate_limiter(AIORateLimiter()).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("departures", departures_cmd))
    app.add_handler(CommandHandler("alerts_on", alerts_on))
    app.add_handler(CommandHandler("alerts_off", alerts_off))

    # Scheduler exists in JobQueue (auto-started)
    app.run_polling()


if __name__ == "__main__":
    main()
