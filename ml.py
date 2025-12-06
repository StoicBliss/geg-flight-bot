import sqlite3
import pandas as pd
from prophet import Prophet
from datetime import datetime
import os

DB_FILE = "flight_data.db"
MODEL_FILE = "departures_model.pkl"


def load_history(flight_type="departure"):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("""
        SELECT timestamp, hour, airline, destination
        FROM flights
        WHERE type=?
    """, conn, params=[flight_type])
    conn.close()

    if df.empty:
        return None

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["ds"] = df["timestamp"].dt.floor("H")
    df["y"] = 1

    df = df.groupby("ds")["y"].sum().reset_index()
    return df


def train_model():
    df = load_history("departure")
    if df is None or len(df) < 12:
        print("Not enough historical data to train.")
        return None

    print("Training Prophet model…")

    model = Prophet(
        daily_seasonality=True,
        weekly_seasonality=True,
        changepoint_prior_scale=0.5
    )
    model.fit(df)

    # Save model
    model.save(MODEL_FILE)
    print("Model saved:", MODEL_FILE)
    return model


def load_trained_model():
    from prophet.serialize import model_from_json
    if not os.path.exists(MODEL_FILE):
        return None
    with open(MODEL_FILE, "r") as f:
        return model_from_json(f.read())


def forecast(hours=12):
    from prophet.serialize import model_to_json

    model = load_trained_model()
    if model is None:
        model = train_model()
        if model is None:
            return None

    future = model.make_future_dataframe(periods=hours, freq="H")
    fc = model.predict(future)
    return fc.tail(hours)[["ds", "yhat"]]
