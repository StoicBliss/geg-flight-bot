# 🚖 GEG Airport Rideshare Bot

**A Telegram bot designed for Uber & Lyft drivers at Spokane International Airport (GEG).**

This bot helps drivers maximize their earnings by predicting peak demand times. Instead of guessing when to drive to the airport, this tool analyzes real-time flight data to tell you exactly when the "rush" (arrivals) or "drop-off wave" (departures) is happening.

## ✨ Features

* **📊 Visual Demand Graphs:** Generates a bar chart showing hourly flight volume for the next 24 hours. Quickly see when the "green bars" (arrivals) spike.
* **🚦 Surge Strategy Score:** Analyzes the next 3 hours of traffic and gives a recommendation: *Low Demand*, *Moderate*, or *High Surge Likely*.
* **⚠️ Delay Watch:** Checks currently scheduled flights for "Delayed" or "Cancelled" statuses so you don't wait in a stagnant queue.
* **✈️ Live Flight Lists:** Retrieve the next 10 scheduled arrivals or departures with airline and flight number details.
* **💾 Smart Caching:** Caches API responses for 45 minutes to preserve free-tier API credits while keeping data relevant.

## 📱 Command List

| Command | Description | Best Time to Use |
| :--- | :--- | :--- |
| `/start` | Initializes the bot and shows the menu. | First time setup. |
| `/graph` | **(Best Feature)** Sends a visual bar chart of arrivals vs. departures. | Before starting your shift to plan your breaks. |
| `/status` | Calculates a "Surge Score" based on upcoming passenger volume. | After a drop-off, to decide if you should stay or go back to the city. |
| `/delays` | Lists active delays or cancellations. | If the TNC queue isn't moving as fast as expected. |
| `/arrivals` | Lists the specific times and flight numbers of the next 10 landing planes. | To see which airlines are coming in (e.g., larger Deltas vs. smaller Alaskas). |
| `/departures` | Lists the next 10 flights taking off. | To anticipate demand from downtown hotels to the airport. |

## 🛠️ Technology Stack

* **Language:** Python 3.10+
* **Libraries:** `python-telegram-bot`, `pandas`, `matplotlib`, `requests`
* **Data Source:** AviationStack API
* **Hosting:** Render (Web Service)

## 🚀 Installation & Local Setup

If you want to run this bot on your own computer for testing:

1.  **Clone the repository**
    ```bash
    git clone [https://github.com/yourusername/geg-flight-bot.git](https://github.com/yourusername/geg-flight-bot.git)
    cd geg-flight-bot
    ```

2.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Set Environment Variables**
    You need to set your API keys. On Mac/Linux:
    ```bash
    export TELEGRAM_TOKEN="your_telegram_bot_token"
    export AVIATION_API_KEY="your_aviationstack_key"
    ```
    *(On Windows, use `set TELEGRAM_TOKEN=...`)*

4.  **Run the Bot**
    ```bash
    python main.py
    ```

## ☁️ Deployment (Render.com)

This bot is optimized for deployment on Render's free tier.

1.  **Create a Web Service** on [Render](https://render.com).
2.  **Connect your GitHub repo.**
3.  **Settings:**
    * **Runtime:** Python 3
    * **Build Command:** `pip install -r requirements.txt`
    * **Start Command:** `python main.py`
4.  **Environment Variables:**
    Add the following keys in the Render dashboard:
    * `TELEGRAM_TOKEN`: (Get this from @BotFather)
    * `AVIATION_API_KEY`: (Get this from AviationStack)

> **Note:** Since this bot uses `polling`, Render's free tier may spin it down after inactivity. Use a free uptime monitor (like UptimeRobot) to ping your Render URL every 5 minutes to keep it awake.

## 📈 How to Read the Graph

When you run `/graph`, you will see two colors:
* **Green Bars (Arrivals):** This is your **Money Time**. These passengers need rides *away* from the airport. Be in the TNC Waiting Lot 15-20 minutes before a large green spike.
* **Red Bars (Departures):** These passengers are leaving the city. Position yourself in downtown Spokane or near major hotels 1.5 - 2 hours before a large red spike to catch these rides *to* the airport.

## 📝 License

This project is open source. Feel free to fork and modify for other airports!
