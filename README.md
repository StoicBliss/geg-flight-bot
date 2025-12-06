# 🚖 GEG Airport Pro Driver Assistant

**The ultimate bot for Uber, Lyft, and Rideshare drivers at Spokane International Airport (GEG).**

This is not just a flight tracker—it is a strategy tool. It filters out cargo/private jets to show you only **passenger volume**, predicts exactly **when** passengers will be curbside, and tells you **which zone** (Concourse A/B vs C) to target.

---

## ⚡️ New Pro Features (v3.1)

* **📍 Zone Targeting:** The bot knows which airlines fly out of which terminals.
    * *Example:* "Location: Zone C" for Alaska Airlines arrivals.
    * *Example:* "Location: Zone A/B" for Delta/United/Southwest.
* **⏱️ Curbside Timer:** Planes land on the runway, but passengers land on the curb ~20 minutes later. The bot calculates the "Ready" time so you don't wait unpaid.
* **📝 Clean Terminal Display:** Professional, easy-to-scan text format. No clutter, just the data you need while driving.
* **🌤️ Live Weather:** Checks current airport conditions. (Rain/Snow = Slower traffic & higher demand).
* **🛡️ Passenger-Only Filter:** Automatically hides FedEx, UPS, and private charter flights that don't need rides.

---

## 📱 Command Guide

| Command | Description | Driver Strategy |
| :--- | :--- | :--- |
| `/start` | Show the main menu. | |
| `/status` | **(Top Command)** Analyzes the next 3 hours of demand, checks weather, and recommends a strategy. | Use this after every drop-off to decide your next move. |
| `/graph` | Generates a visual bar chart of Demand vs. Time. | Use this before your shift to plan your breaks around the dead times. |
| `/arrivals` | Lists the next 10 landing planes with **Zone** and **Curbside Time**. | Use this to see if the "Green Bar" on the graph is Alaska (Zone C) or Delta (Zone A/B). |
| `/departures` | Lists the next 10 takeoff flights. | Use this to predict demand **FROM** downtown/hotels **TO** the airport. |
| `/delays` | Scans for "Delayed" or "Cancelled" statuses on passenger flights. | Use this if the TNC queue is moving abnormally slow. |

---

## 📖 How to Read the Data

### **Arrivals (The "Money" Screen)**
The bot gives you two times. "Touchdown" is when the plane lands. "Ready" is when you should be at the curb.

> **Alaska** (AS128)
> Touchdown: `14:00` | Ready: `14:20`
> Location: Zone C
>
> **Delta** (DL992)
> Touchdown: `14:15` | Ready: `14:35`
> Location: Zone A/B

### **Departures (Drop-offs)**
A simple list of when planes are leaving. Plan to be in the city 90 minutes before these times.

> `16:00` • **Southwest** (WN112)
> `16:15` • **Alaska** (AS442)
> `16:30` • **American** (AA512)

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

## 📝 License
Open Source. Happy Driving! 🚙💨
