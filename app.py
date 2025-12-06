from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# -----------------------
# Bot token
# -----------------------
TOKEN = "8377026663:AAFA0PHG4VguKwlyborjSjG2GlUCZ1CznGM"

bot = Bot(TOKEN)
app = Flask(__name__)

# -----------------------
# Telegram command handlers
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! Bot is running.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send /start to begin.")

# -----------------------
# Build Telegram application
# -----------------------
application = ApplicationBuilder().token(TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))

# -----------------------
# Webhook route
# -----------------------
@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    application.update_queue.put(update)  # send update to the app queue
    return "ok", 200

# -----------------------
# Optional health check
# -----------------------
@app.route("/", methods=["GET"])
def index():
    return "Bot is running", 200

# -----------------------
# Local testing (optional)
# -----------------------
if __name__ == "__main__":
    app.run(port=5000)
