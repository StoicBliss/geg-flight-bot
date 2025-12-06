import asyncio
import logging
import os
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from scraper import scrape_flights
from db import init_db, save_flights
from ml import forecast, train_model
from flight_plot import plot_forecast

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")

scheduler = AsyncIOScheduler()


# ------------------------------
# Commands
# ------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 GEG Flight Bot Ready!\n"
        "Commands:\n"
        "/departures – current departures\n"
        "/arrivals – current arrivals\n"
        "/forecast – next 12h ML forecast\n"
    )


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
    hours = 12
    if context.args and context.args[0].isdigit():
        hours = int(context.args[0])

    await update.message.reply_text("🧠 Loading forecast…")

    fc = forecast(hours)
    if fc is None:
        await update.message.reply_text("Not enough data to forecast.")
        return

    lines = ["📈 *Forecasted Demand*"]
    for _, row in fc.iterrows():
        lines.append(f"{row['ds']:%b %d %I %p}: {row['yhat']:.1f} flights")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    img = plot_forecast(fc)
    await update.message.reply_photo(img)


# ------------------------------
# Scheduler Setup
# ------------------------------

async def on_startup(app):
    """Runs once when Telegram bot starts; safe place to start scheduler."""

    if scheduler.running:
        return  # already running

    # Nightly ML training (2 AM Pacific)
    scheduler.add_job(
        train_model,
        CronTrigger(hour=2, minute=0, timezone="US/Pacific"),
        id="nightly_training"
    )

    # Scrape departures every 30 min
    scheduler.add_job(
        lambda: save_flights(scrape_flights("departure"), "departure"),
        CronTrigger(minute="*/30", timezone="US/Pacific"),
        id="scrape_departures"
    )

    # Scrape arrivals every 30 min
    scheduler.add_job(
        lambda: save_flights(scrape_flights("arrival"), "arrival"),
        CronTrigger(minute="*/30", timezone="US/Pacific"),
        id="scrape_arrivals"
    )

    scheduler.start()
    print("Scheduler started successfully.")


# ------------------------------
# Main
# ------------------------------

def main():
    init_db()

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(on_startup)   # <--- FIX: Scheduler starts here
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("departures", departures))
    app.add_handler(CommandHandler("arrivals", arrivals))
    app.add_handler(CommandHandler("forecast", forecast_cmd))

    print("Bot running.")
    app.run_polling()


if __name__ == "__main__":
    main()
