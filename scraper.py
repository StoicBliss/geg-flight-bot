import requests
from bs4 import BeautifulSoup
from datetime import datetime

URL = "https://spokaneairports.net/flight-status/"


def scrape_flights(flight_type="departure"):
    r = requests.get(URL, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")

    tab_id = "departures" if flight_type == "departure" else "arrivals"
    table = soup.find("div", id=tab_id)

    flights = []

    for row in table.select("tbody tr"):
        cols = row.find_all("td")
        if len(cols) < 4:
            continue

        time_raw = cols[0].text.strip()
        airline = cols[1].text.strip()
        destination = cols[2].text.strip()

        # Convert "10:45 AM" → hour=10
        try:
            dt = datetime.strptime(time_raw, "%I:%M %p")
            hour = dt.hour
        except:
            continue

        flights.append({
            "airline": airline,
            "destination": destination,
            "hour": hour
        })

    return flights
