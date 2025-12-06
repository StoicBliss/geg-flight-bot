import requests
from collections import defaultdict
from datetime import datetime
import pytz

def get_departures_grouped():
    url = "https://spokaneairports.net/wp-json/airport/flights?type=departures"
    r = requests.get(url, timeout=10)
    data = r.json().get("data", [])

    if not data:
        return "No departure data available right now."

    tz = pytz.timezone("America/Los_Angeles")
    groups = defaultdict(int)

    for flight in data:
        sched = flight.get("scheduled")
        if not sched:
            continue

        dt = datetime.fromisoformat(sched).astimezone(tz)
        hour = dt.strftime("%I %p").lstrip("0")

        groups[hour] += 1

    # Sort by hour string time order
    ordered = []
    for hour in sorted(groups.keys(), key=lambda h: datetime.strptime(h, "%I %p")):
        ordered.append(f"{hour}: {groups[hour]} departures")

    return "\n".join(ordered)
