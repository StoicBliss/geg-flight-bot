import sqlite3
import pandas as pd
from prophet import Prophet
from datetime import datetime, timedelta

DB_FILE = "flight_data.db"

def load_history(flight_type="departure", filter_term=None):
    conn = sqlite3.connect(DB_FILE)
    query = """
        SELECT hour, airline, destination, timestamp
        FROM flights
        WHERE type=?
    """
    params = [flight_type]

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    if df.empty:
        return None

    # Convert UTC timestamp to datetime
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    if filter_term:
        f = filter_term.lower()
        df = df[
            df["airline"].str.lower().str.contains(f)
            | df["destination"].str.lower().str.contains(f)
        ]

        if df.empty:
            return None

    # Convert hour-of-day record into proper datetime for Prophet
    df["ds"] = df["timestamp"].dt.floor("H")
    df["y"] = 1  # each row is one flight occurrence

    # Aggregate: Prophet requires summed values per timestamp
    df = df.groupby("ds")["y"].sum().reset_index()

    return df


def forecast_demand(
    flight_type="departure",
    future_hours=12,
    filter_term=None
):
    df = load_history(flight_type, filter_term)
    if df is None or df.empty or len(df) < 10:
        return None

    # Train the Prophet model
    model = Prophet(
        daily_seasonality=True,
        weekly_seasonality=True,
        changepoint_prior_scale=0.5
    )
    model.fit(df)

    # Future dataframe
    future = model.make_future_dataframe(periods=future_hours, freq="H")
    forecast = model.predict(future)

    # Extract next N hours
    fc = forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]].tail(future_hours)

    return fc
