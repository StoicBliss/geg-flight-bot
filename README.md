# 🚖 GEG Airport Pro Driver Assistant

**The ultimate "Co-Pilot" bot for Uber, Lyft, and Rideshare drivers at Spokane International Airport (GEG).**

This is not just a flight tracker—it is a strategy tool. It filters out cargo/private jets to show you only **passenger volume**, predicts exactly **when** passengers will be curbside, and tells you **which zone** (Concourse A/B vs C) to target.

---

## ⚡️ New Pro Features (v3.0)

* **📍 Zone Targeting:** The bot knows which airlines fly out of which terminals.
    * *Example:* "Go to Zone C" for Alaska Airlines arrivals.
    * *Example:* "Go to Zone A/B" for Delta/United/Southwest.
* **⏱️ Curbside Timer:** Planes land on the runway, but passengers land on the curb 20 minutes later. The bot calculates the "Ready" time so you don't wait unpaid.
* **🌤️ Live Weather:** Checks current airport conditions. (Rain/Snow = Slower traffic & higher demand).
* **🛡️ Passenger-Only Filter:** Automatically hides FedEx, UPS, and private charter flights that don't need rides.

---

## 📱 Command Guide

| Command | Description | Driver Strategy |
| :--- | :--- | :--- |
| `/start` | Show the main menu. | |
| `/status` | **(Top Command)** Analyzes the next 3 hours of demand, checks weather, and recommends a strategy. | Use this after every drop-off to decide your next move. |
| `/graph` | Generates a visual bar chart of Demand vs. Time. | Use this before your shift to plan your breaks around the dead times. |
| `/arrivals` | Lists the next 12 landing planes with **Zone** and **Curbside Time**. | Use this to see if the "Green Bar" on the graph is Alaska (Zone C) or Delta (Zone A/B). |
| `/departures` | Lists the next 12 takeoff flights. | Use this to predict demand **FROM** downtown/hotels **TO** the airport. |
| `/delays` | Scans for "Delayed" or "Cancelled" statuses on passenger flights. | Use this if the TNC queue is moving abnormally slow. |

---

## 🗺️ The GEG Zone Map

Spokane Airport is split into two main passenger pickup areas. The bot will tell you which one to target based on the incoming flight.

| Zone | Airlines | Location for Driver |
| :--- | :--- | :--- |
| **Zone C** | **Alaska**, American (some), Allegiant | **North End.** Turn left at the split towards the "C" baggage claim area. |
| **Zone A/B** | **Southwest, Delta, United** | **South/Center.** The main rotunda area. |

> **Note:** Airlines sometimes move gates. If you notice an airline has moved permanently, you can update the `PASSENGER_AIRLINES` dictionary in `main.py`.

---

## 🚀 Deployment Guide (Render.com)

This bot is designed to run 24/7 on [Render's Free Tier](https://render.com).

### 1. Prerequisites
* A **Telegram Bot Token** (from @BotFather).
* An **AviationStack API Key** (Free Plan).
* A GitHub account.

### 2. Setup
1.  **Fork/Clone** this repo to your GitHub.
2.  Create a **New Web Service** on Render.
3.  Connect your GitHub repo.
4.  **Settings:**
    * **Runtime:** Python 3
    * **Build Command:** `pip install -r requirements.txt`
    * **Start Command:** `python main.py`
5.  **Environment Variables:**
    * `TELEGRAM_TOKEN`: *Your Bot Token*
    * `AVIATION_API_KEY`: *Your API Key*
    * `PORT`: `8080` (Optional, Render sets this automatically)

### 3. Preventing "Sleep Mode"
Render's free tier spins down after 15 minutes of inactivity. To keep it alive 24/7:
1.  Deploy the bot.
2.  Copy your Render URL (e.g., `https://geg-flight-bot.onrender.com`).
3.  Create a free account on **UptimeRobot**.
4.  Add a new "HTTP(s)" monitor that pings your Render URL every 5 minutes.
5.  *Result:* The bot stays awake forever for free.

---

## 🛠️ Local Installation (For Testing)

1.  Clone the repo:
    ```bash
    git clone [https://github.com/yourname/geg-flight-bot.git](https://github.com/yourname/geg-flight-bot.git)
    ```
2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
3.  Set keys (Mac/Linux):
    ```bash
    export TELEGRAM_TOKEN="your_token"
    export AVIATION_API_KEY="your_key"
    ```
4.  Run:
    ```bash
    python main.py
    ```

---

## ❓ FAQ

**Q: Why does the graph sometimes show "No Data"?**
A: The AviationStack Free Tier has a monthly limit. The bot caches data for 45 minutes to save your credits. If you run out of credits, you will need to wait for the next month or upgrade the API plan.

**Q: Can I use this for Seattle (SEA)?**
A: Yes! Just change `AIRPORT_IATA = 'GEG'` to `AIRPORT_IATA = 'SEA'` in `main.py`. (You will also need to update the `PASSENGER_AIRLINES` list with Seattle's terminal info).

**Q: What is the "Curbside Time"?**
A: It is `Landing Time + 20 Minutes`. This is the average time it takes for a passenger to taxi to the gate, walk off the plane, and get to the curb.

---

## 📝 License
Open Source. Happy Driving! 🚙💨
