import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from scraper import scrape_flights
from db import init_db, save_flights
from ml import train_model, forecast
from flight_plot import plot_forecast

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask, request

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("8377026663:AAFA0PHG4VguKwlyborjSjG2GlUCZ1CznGM")
WEBHOOK_URL = os.getenv("https://geg-flight-bot.onrender.com/webhook")   # e.g. https://geg-flight-bot.onrender.com/webhook
PORT = int(os.getenv("PORT", 8000))

scheduler = AsyncIOScheduler()

# ------------------------------
# Commands
# ------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("GEG Bot online! Webhook active.")

async def departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    flights = scrape_flights("departure")
    save_flights(flights, "departure")
    txt = ["✈️ *Departures*"]
    for f in flights:
        txt.append(f"{f['hour']:02d}:00 – {f['airline']} → {f['destination']}")
    await update.message.reply_text("\n".join(txt), parse_mode="Markdown")

async def arrivals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    flights = scrape_flights("arrival")
    save_flights(flights, "arrival")
    txt = ["📉 *Arrivals*"]
    for f in flights:
        txt.append(f"{f['hour']:02d}:00 – {f['airline']} from {f['destination']}")
    await update.message.reply_text("\n".join(txt), parse_mode="Markdown")

async def forecast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 Computing forecast…")
    fc = forecast(12)
    img = plot_forecast(fc)
    await update.message.reply_photo(img)

# ------------------------------
# Schedule jobs (safe inside loop)
# ------------------------------

async def on_start(app):
    if not scheduler.running:
        scheduler.add_job(train_model, CronTrigger(hour=2, timezone="US/Pacific"))
        scheduler.add_job(lambda: save_flights(scrape_flights("departure"), "departure"),
                          CronTrigger(minute="*/30", timezone="US/Pacific"))
        scheduler.add_job(lambda: save_flights(scrape_flights("arrival"), "arrival"),
                          CronTrigger(minute="*/30", timezone="US/Pacific"))
        scheduler.start()
        print("Scheduler started.")

# ------------------------------
# Flask Webhook Server (REQUIRED)
# ------------------------------

flask_app = Flask(__name__)
tg_app = None  # will be set in main()


@flask_app.post("/webhook")
def webhook_handler():
    """Handle incoming Telegram webhook updates."""
    json_data = request.get_json(force=True)
    asyncio.get_event_loop().create_task(tg_app.process_update(Update.de_json(json_data, tg_app.bot)))
    return "ok", 200

# ------------------------------
# MAIN — start webhook bot + flask server
# ------------------------------

def main():
    global tg_app
    init_db()

    tg_app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(on_start)
        .build()
    )

    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(CommandHandler("departures", departures))
    tg_app.add_handler(CommandHandler("arrivals", arrivals))
    tg_app.add_handler(CommandHandler("forecast", forecast_cmd))

    # Set the webhook
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        tg_app.bot.set_webhook(f"{WEBHOOK_URL}")
    )

    print(f"Webhook set to {WEBHOOK_URL}")

    # Run Flask (Render will expose it)
    flask_app.run(host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
