import sqlite3
from datetime import datetime
from collections import Counter

DB_FILE = "flight_data.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS flights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT,               -- departure or arrival
            airline TEXT,
            flight TEXT,
            destination TEXT,
            hour INTEGER,
            timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_flights(flight_list):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    now = datetime.utcnow().isoformat()

    for f in flight_list:
        c.execute("""
            INSERT INTO flights (type, airline, flight, destination, hour, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (f["type"], f["airline"], f["flight"], f["destination"], f["hour"], now))

    conn.commit()
    conn.close()


def hourly_stats(flight_type="departure"):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT hour FROM flights WHERE type=?
    """, (flight_type,))
    hours = [row[0] for row in c.fetchall()]
    conn.close()
    return Counter(hours)


def predict_next_peak(type="departure"):
    """
    Simple prediction:
    Picks the hour with the highest historical frequency.
    """
    stats = hourly_stats(type)
    if not stats:
        return None

    predicted_hour = max(stats, key=lambda h: stats[h])
    predicted_count = stats[predicted_hour]
    return predicted_hour, predicted_count
