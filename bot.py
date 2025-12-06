import os
import asyncio
from fastapi import FastAPI
import uvicorn
from telegram.ext import ApplicationBuilder

# Telegram bot setup
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

# Start Telegram polling in the background
async def start_bot():
    await application.initialize()
    await application.start()
    await application.updater.start_polling()

asyncio.create_task(start_bot())

# Minimal FastAPI app just to bind a port
app = FastAPI()

@app.get("/")
def root():
    return {"status": "bot running"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))  # Render sets PORT automatically
    uvicorn.run(app, host="0.0.0.0", port=port)
