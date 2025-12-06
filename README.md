# 🚖 GEG Airport Pro Driver Assistant (v5.0)

**The ultimate strategy tool for Uber, Lyft, and Rideshare drivers at Spokane International Airport (GEG).**

Unlike standard flight trackers, this bot is built specifically for rideshare economics. It filters out non-passenger cargo flights, calculates exactly when passengers will be curbside, and detects "Surge Clusters"—moments when multiple planes land simultaneously, creating high demand.

**Created by: Abu Sayeed Bin Farhad Shafee**

---

## ⚡️ Key Features

### 1. ⚡️ Surge Cluster Detection
The bot automatically analyzes the flight schedule to find "clusters"—moments when 3 or more planes land within a 20-minute window. It highlights these in your feed with a **⚡️ CLUSTER ALERT** visual. These are the golden windows for high-fare rides.

### 2. 💰 Best Shift Predictor
Stop guessing when to drive. The `/status` command analyzes the next 24 hours of flight data and generates a "Best Times to Work" summary, identifying the top 3 busiest hours of the day.

### 3. 📍 Intelligent Zone Targeting
Spokane Airport is split into two distinct pickup zones. The bot tells you exactly where to drive based on the airline:
* **Zone C (North):** Alaska, American, Frontier.
* **Zone A/B (South):** Delta, United, Southwest, Allegiant, Sun Country.

### 4. ⏱️ "Curbside" Readiness Timer
A plane landing on the runway doesn't mean a passenger is ready. The bot adds a smart buffer (~20 mins) to the arrival time, showing you the "Ready" time so you don't wait unpaid at the curb.

### 5. 🗺️ One-Tap Navigation
Includes a specific `/navigate` command that instantly opens Google Maps with coordinates set to the official GEG Rideshare (TNC) Waiting Lot.

### 6. 🌤️ Live Weather Integration
Fetches real-time weather conditions at the airport. Use this to anticipate slower traffic during snow/rain or higher demand during storms.

---

## 📱 Command List

| Command | Description | Strategy Note |
| :--- | :--- | :--- |
| `/status` | **Start Here.** Shows Weather, Demand Score, and "Best Shifts." | Check this before leaving your house. |
| `/arrivals` | Lists next 12 landings with **Surge Clusters** & **Zones**. | Use this to time your drive from the waiting lot to the curb. |
| `/departures` | Lists next 12 takeoffs. | Use this to predict drop-off demand from downtown to GEG. |
| `/graph` | Generates a visual Demand Bar Chart (Next 24h). | Great for planning breaks around "dead" hours. |
| `/navigate` | Opens Google Maps to the TNC Waiting Lot. | One-tap GPS setup. |
| `/delays` | Scans for "Delayed" or "Cancelled" flights. | Check this if the queue is moving unexpectedly slow. |

---

## 📖 How to Read the Data

### **Arrivals (The "Money" Screen)**
The bot gives you two specific times for every flight:
* **Touchdown:** When the wheels hit the runway.
* **Ready:** The estimated time passengers are actually at the curb.

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

---

## 🗺️ GEG Zone Reference (Official)

| Zone | Airlines | Driver Location |
| :--- | :--- | :--- |
| **Zone C** | **Alaska, American, Frontier** | **North End.** Turn left at the split towards Concourse C. |
| **Zone A/B** | **Delta, United, Southwest, Allegiant, Sun Country** | **South/Center.** The main rotunda pickup area. |

---

## 🚀 Installation & Deployment

This project is optimized for Python 3.10+ and requires the `AviationStack` API.

### 1. Prerequisites
* **Telegram Bot Token:** Get this from @BotFather.
* **AviationStack API Key:** Get a free API key from AviationStack.

### 2. Local Setup
```bash
git clone [https://github.com/yourusername/geg-driver-assistant.git](https://github.com/yourusername/geg-driver-assistant.git)
cd geg-driver-assistant
pip install -r requirements.txt
export TELEGRAM_TOKEN="your_token_here"
export AVIATION_API_KEY="your_key_here"
python main.py
