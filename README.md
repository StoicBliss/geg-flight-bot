# 🚖 GEG Airport Pro Driver Assistant (v4.0)

**The ultimate telegram bot for Uber, Lyft, and Rideshare drivers at Spokane International Airport (GEG).**

This is not just a flight tracker—it is a strategy tool. It filters out cargo/private jets to show you only **passenger volume**, predicts exactly **when** passengers will be curbside, and detects **Surge Clusters** (when multiple planes land at once).

---

## ⚡️ New in Version 4.0

* **⚡️ Surge Clusters:** The bot automatically detects when 3+ planes land within a 20-minute window and inserts a visual **CLUSTER ALERT** in your list. These are your best opportunities for high fares.
* **💰 Best Shift Predictor:** The `/status` command now analyzes the entire day's schedule and lists the **Top 3 Busiest Hours** to work.
* **🗺️ One-Tap Navigation:** A new `/navigate` command (and button) instantly opens Google Maps to the GEG Rideshare (TNC) Waiting Lot.
* **📝 Clean Terminal Display:** Professional, easy-to-scan text format. No clutter, just the data you need while driving.

---

## 📱 Command Guide

| Command | Description | Driver Strategy |
| :--- | :--- | :--- |
| `/status` | **(Start Here)** Shows Weather, Surge Score, and the **Best Times to Work Today**. | Check this before leaving your house. |
| `/navigate` | Opens Google Maps to the TNC Waiting Lot. | Use this when you are ready to head to the airport. |
| `/arrivals` | Lists the next 12 landings with **Surge Clusters**, **Zones**, and **Curbside Times**. | Use this to time your drive from the waiting lot to the curb. |
| `/departures` | Lists the next 12 takeoff flights. | Use this to predict demand **FROM** downtown hotels **TO** the airport. |
| `/graph` | Generates a visual bar chart of Demand vs. Time (Next 24h). | Use this to plan your breaks around the dead times. |
| `/delays` | Scans for "Delayed" or "Cancelled" statuses. | Use this if the TNC queue is moving abnormally slow. |

---

## 📖 How to Read the Data

### **1. The "Money" Screen (Arrivals)**
The bot calculates two specific times for every flight:
* **Touchdown:** When the wheels hit the runway.
* **Ready:** ~20 minutes later (when passengers are actually at the curb).

**Example Output:**
> **Delta** (DL992)
> Touchdown: `14:15` | Ready: `14:35`
> Location: Zone A/B
>
> ⚡️ **SURGE CLUSTER DETECTED** ⚡️
>
> **United** (UA341)
> Touchdown: `14:20` | Ready: `14:40`
> Location: Zone A/B

### **2. The Status Screen**
Quickly see if it's worth driving right now.

> 🌤 **Weather:** Overcast +2°C
> 🚦 **Current Status:** 8 Arrivals (High Demand)
> 🔥 **HIGH SURGE LIKELY**
>
> 💰 **Best Times Today:** 14:00, 16:00, 21:00

---

## 🗺️ The GEG Zone Map

Spokane Airport is split into two main passenger pickup areas. The bot will tell you which one to target based on the incoming flight.

| Zone | Airlines | Location for Driver |
| :--- | :--- | :--- |
| **Zone C** | **Alaska**, American (some), Allegiant | **North End.** Turn left at the split towards the "C" baggage claim area. |
| **Zone A/B** | **Southwest, Delta, United** | **South/Center.** The main rotunda area. |

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


## 📝 License
Open Source. Happy Driving! 🚙💨
