# 🚖 GEG Airport Pro Driver Assistant (v6.0 - Final)

**The ultimate strategy tool for Uber, Lyft, and Rideshare drivers at Spokane International Airport (GEG).**

This bot provides highly accurate, localized data to maximize your earnings. It eliminates noise (cargo/private jets), synchronizes to Pacific Time, and flags high-demand "Surge Clusters."

**Created by: Abu Sayeed Bin Farhad Shafee**

---

## ⚡️ Key Features

### 1. ⏱️ Real-Time Pacific Sync
The bot strictly filters out all past flights and synchronizes all times (Touchdown, Ready, Status) to the **US/Pacific Time Zone**, eliminating confusion caused by server time.

### 2. ⚡️ Surge Cluster Detection
The bot automatically detects when 3 or more planes land within a 20-minute window and inserts a visual **CLUSTER ALERT** in your feed. This identifies peak instant surge opportunities.

### 3. 💰 Best Shift Predictor
The `/status` command analyzes the entire 24-hour schedule and calculates the **Top 3 Busiest Hours** of the day for passenger arrivals.

### 4. 🎯 Intelligent Zone Targeting (Verified)
The system knows which airlines are assigned to which concourses. The zones have been verified against the official Spokane Airport data:
* **Zone C (North):** Alaska, American, Frontier.
* **Zone A/B (South):** Delta, United, Southwest, Allegiant, Sun Country.

### 5. 🌡️ Reliable Weather Source
Switched to **OpenWeatherMap** for fast, accurate airport weather readings (temperature and conditions) displayed in the `/status` report.

### 6. 🗺️ One-Tap Navigation
The `/navigate` command instantly provides a button to open Google Maps, pre-set to the official GEG TNC Waiting Lot location.

---

## 📱 Command List

| Command | Description | Strategy Note |
| :--- | :--- | :--- |
| `/status` | **(Start Here)** Shows Weather, Surge Score, and "Best Shifts." | Check this before leaving your house. |
| `/arrivals` | Lists next 12 landings with **Surge Clusters** & **Curbside Times**. | Use this to time your drive from the waiting lot to the curb. |
| `/departures` | Lists next 12 takeoffs. | Use this to predict drop-off demand from downtown to GEG. |
| `/graph` | Generates a visual Demand Bar Chart (Next 24h). | Great for planning breaks around the dead times. |
| `/navigate` | Opens Google Maps to the TNC Waiting Lot. | One-tap GPS setup. |
| `/delays` | Scans for "Delayed" or "Cancelled" flights. | Check this if the queue is moving unexpectedly slow. |

---

## 📖 How to Read the Data

### **Arrivals (The "Money" Screen)**
The bot calculates two specific times for every flight:
* **Touchdown:** When the wheels hit the runway (Scheduled Arrival).
* **Ready:** The estimated time the passenger is actually at the curb (**Touchdown + 20 minutes**).

**Example Output:**
> **Delta** (DL992)
> Touchdown: `14:15` | Ready: `14:35`
> Location: Zone A/B
>
> ⚡️ **SURGE CLUSTER DETECTED** ⚡️
>
> **Alaska** (AS128)
> Touchdown: `14:25` | Ready: `14:45`
> Location: Zone C

---

## 🗺️ GEG Zone Reference (Official)

| Zone | Airlines | Driver Pickup Zone |
| :--- | :--- | :--- |
| **Zone C** | **Alaska (AS), American (AA), Frontier (F9)** | **North End** (Separate Concourse) |
| **Zone A/B** | **Delta (DL), United (UA), Southwest (WN), Allegiant (G4), Sun Country (SY)** | **Center/South End** (Main Rotunda Area) |

---

## 🚀 Installation & Deployment

This project is optimized for Python 3.10+ and requires two API keys.

### 1. Prerequisites
* **Telegram Bot Token**
* **AviationStack API Key** (for flight data)
* **OpenWeatherMap API Key** (for weather data)

### 2. Deployment (Render)
1.  Fork this repository.
2.  Create a **New Web Service** on Render.
3.  Set the **Build Command** to `pip install -r requirements.txt`.
4.  Set the **Start Command** to `python main.py`.
5.  **Environment Variables:** Add all three required keys (`TELEGRAM_TOKEN`, `AVIATION_API_KEY`, **`OPENWEATHER_API_KEY`**).

---

## 📝 Credits & License
**Author:** Abu Sayeed Bin Farhad Shafee  
**License:** Open Source (MIT)
