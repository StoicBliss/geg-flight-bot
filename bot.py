from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hi! I'm your GEG Flight Tracker bot. Use /departures to see flight peaks.")

async def departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = get_departures()
    message = departures_by_hour(df)
    await update.message.reply_text(message)

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("departures", departures))

print("Bot started...")
app.run_polling()
