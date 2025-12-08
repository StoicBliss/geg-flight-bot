# 🚕 GEG Airport Pro Driver Assistant

A specialized Telegram bot designed for **Uber & Lyft drivers** at **Spokane International Airport (GEG)**. 

This tool helps drivers maximize earnings by predicting peak demand times, visualizing flight volume, and identifying exactly where and when passengers will be curbside. Unlike generic flight trackers, this bot filters out cargo flights, codeshares, and private charters to focus **100% on passenger demand**.

---

## 🚀 Features

### 🚦 Intelligent Demand Strategy
* **Surge Score:** Analyzes incoming flight volume for the next hour to recommend a strategy (`Stay Downtown`, `Head to Cell Lot`, or `GO NOW`).
* **Weather Integration:** Factors in rain/snow data from OpenWeatherMap to predict demand surges.
* **Navigation:** Includes a one-tap button to navigate directly to the **GEG Cell Phone Waiting Lot**.

### ✈️ Real-Time Flight Boards
* **True Pickup Time:** Automatically calculates the "Curbside Time" (Landing + 20 mins) for arrivals to prevent unpaid waiting.
* **Zone Targeting:** Identifies whether passengers are at **Zone A/B (Rotunda)** or **Zone C (North)** based on airline data.
* **Smart Filtering:** Removes FedEx, UPS, and duplicate Codeshare listings (e.g., hiding a BA flight that is actually an Alaska plane).

### 🚨 Trouble Monitor
* **Dedicated Delay Feed:** A specific command (`/delays`) to see only flights delayed by >15 minutes or cancelled.
* **Live Status Icons:** ⚠️ and 🔴 icons on main boards highlight issues instantly.

### 🛡️ Reliability
* **AirLabs Schedules API:** Uses future schedule data to prevent "ghost flights" (missing future data).
* **Caching System:** Caches data for 15 minutes to respect API rate limits (1,000 req/month Free Tier).
* **Keep-Alive Server:** Built-in Flask server to prevent the bot from sleeping on free cloud hosting platforms.

---

## 🛠️ Tech Stack

* **Language:** Python 3.10+
* **Core Library:** `python-telegram-bot` (v20+ Async)
* **Web Server:** `Flask` (for health checks & port binding)
* **Data Processing:** `pandas`, `pytz`, `requests`
* **APIs:**
    * [AirLabs.co](https://airlabs.co/) (Flight Schedules)
    * [OpenWeatherMap](https://openweathermap.org/) (Weather)
    * Telegram Bot API

---

## ⚙️ Configuration & Prerequisites

You need API keys from the following services (Free Tiers work for all):

1.  **Telegram Bot Token:** Get from [@BotFather](https://t.me/BotFather).
2.  **AirLabs API Key:** Get from [AirLabs](https://airlabs.co/).
3.  **OpenWeatherMap API Key:** Get from [OpenWeatherMap](https://openweathermap.org/api).

### Environment Variables
The bot relies on environment variables for security. Do not hardcode keys in `bot.py`.

| Variable | Description |
| :--- | :--- |
| `TELEGRAM_TOKEN` | Your Telegram Bot Token |
| `AIRLABS_API_KEY` | Your AirLabs Key |
| `WEATHER_API_KEY` | Your OpenWeatherMap Key |
| `PORT` | (Optional) Port for Flask server. Render sets this automatically. |

---

## 📦 Local Installation

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/yourusername/geg-driver-bot.git](https://github.com/yourusername/geg-driver-bot.git)
    cd geg-driver-bot
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Set Environment Variables (Mac/Linux):**
    ```bash
    export TELEGRAM_TOKEN="your_token_here"
    export AIRLABS_API_KEY="your_key_here"
    export WEATHER_API_KEY="your_key_here"
    ```

4.  **Run the bot:**
    ```bash
    python bot.py
    ```

---

## ☁️ Deployment (Render.com)

This bot is optimized for **Render's Free Tier**.

1.  Create a new **Web Service** (Not Background Worker) on Render.
    * *Note: We use Web Service because the bot runs a Flask server to bind to a port, preventing Render from killing the app for inactivity.*
2.  Connect your GitHub repository.
3.  **Runtime:** Python 3
4.  **Build Command:** `pip install -r requirements.txt`
5.  **Start Command:** `python bot.py`
6.  **Environment Variables:** Add your 3 keys (`TELEGRAM_TOKEN`, etc.) in the Render Dashboard.
7.  Deploy! The bot handles the webhook/polling automatically.

---

## 📱 Bot Commands

| Command | Description |
| :--- | :--- |
| `/start` | Welcome message and dashboard summary. |
| `/status` | Strategy score, weather, and navigation link. |
| `/arrivals` | Board of incoming flights with Pickup Time & Zone. |
| `/departures` | Board of outgoing flights with Drop-off Zone. |
| `/delays` | List of flights delayed >15m or cancelled. |

---

## 📂 Project Structure

```text
geg-driver-bot/
├── bot.py              # Main bot logic, API fetching, and Flask server
├── requirements.txt    # Python dependencies
└── README.md           # Documentation
requirements.txt content:
Plaintext

python-telegram-bot
requests
flask
pytz

## ℹ️ Notes on "Check Screen"
If the bot displays "Zone: Check Screen", it means the flight is operated by a regional partner (like SkyWest) or the API data didn't specify a terminal. These flights often shift between gates, so the driver should check physical airport screens.
---

## ℹ️ Disclaimer: This tool is for informational purposes only. Always obey airport traffic laws and regulations.
---
