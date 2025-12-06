import matplotlib.pyplot as plt
import io

def plot_forecast(forecast_df):
    fig, ax = plt.subplots(figsize=(8,4))
    ax.plot(forecast_df["ds"], forecast_df["yhat"], label="Forecast")
    ax.set_title("Flight Demand Forecast")
    ax.set_ylabel("Expected Flights")
    ax.set_xlabel("Time")
    ax.legend()

    img = io.BytesIO()
    fig.savefig(img, format="png", bbox_inches="tight")
    img.seek(0)
    return img
