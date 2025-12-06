import sqlite3
from datetime import datetime

DB_FILE = "flight_data.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS flights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT, 
        airline TEXT,
        destination TEXT,
        hour INTEGER,
        timestamp TEXT
    )
    """)

    conn.commit()
    conn.close()


def save_flights(flights, flight_type):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    for f in flights:
        c.execute("""
            INSERT INTO flights (type, airline, destination, hour, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (
            flight_type,
            f["airline"],
            f["destination"],
            f["hour"],
            datetime.utcnow().isoformat()
        ))

    conn.commit()
    conn.close()
