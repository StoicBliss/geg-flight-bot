import matplotlib.pyplot as plt
from datetime import datetime

def create_departure_chart(counter):
    hours = list(range(24))
    counts = [counter.get(h, 0) for h in hours]
    labels = [datetime.strptime(str(h), "%H").strftime("%I %p") for h in hours]

    plt.figure(figsize=(12, 6))
    plt.bar(hours, counts, color="#0077CC")
    plt.xticks(hours, labels, rotation=45)
    plt.ylabel("Departures")
    plt.title("GEG Departures by Hour")

    output_path = "departures.png"
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()

    return output_path

