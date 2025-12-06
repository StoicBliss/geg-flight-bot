# Overwrite the existing fetch_aerodatabox_data function in main.py

def fetch_aerodatabox_data():
    """Fetches 12-hour chunks of data for Arrivals AND Departures."""
    if not RAPIDAPI_KEY:
        logging.error("RapidAPI Key missing.")
        return None

    # Fetch window: Now -> Now + 12h
    now = datetime.now(SPOKANE_TZ)
    end = now + timedelta(hours=12)
    
    # AeroDataBox format: YYYY-MM-DDTHH:MM
    time_from = now.strftime('%Y-%m-%dT%H:%M')
    time_to = end.strftime('%Y-%m-%dT%H:%M')
    
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "aerodatabox.p.rapidapi.com"
    }

    endpoints = [
        ("arrival", f"https://aerodatabox.p.rapidapi.com/flights/airports/iata/{AIRPORT_IATA}/{time_from}/{time_to}?direction=Arrival&withPrivate=false"),
        ("departure", f"https://aerodatabox.p.rapidapi.com/flights/airports/iata/{AIRPORT_IATA}/{time_from}/{time_to}?direction=Departure&withPrivate=false")
    ]

    all_flights = []

    for type_label, url in endpoints:
        try:
            response = requests.get(url, headers=headers, timeout=15)
            # CRITICAL DEBUGGING LINE: Check for HTTP error codes
            response.raise_for_status() 
            
            data = response.json()
            
            flight_list = data.get('arrivals') if type_label == 'arrival' else data.get('departures')
            
            if not flight_list: continue

            # ... (rest of parsing logic remains unchanged) ...
            for f in flight_list:
                try:
                    time_obj = f.get('movement', {})
                    time_str = time_obj.get('revisedTime') or time_obj.get('scheduledTime')
                    
                    if not time_str: continue 
                    
                    dt = datetime.fromisoformat(time_str)
                    
                    if dt.tzinfo is None:
                        dt = SPOKANE_TZ.localize(dt)
                    else:
                        dt = dt.astimezone(SPOKANE_TZ)

                    airline_obj = f.get('airline', {})
                    airline_name = airline_obj.get('name', 'Unknown')
                    airline_iata = airline_obj.get('iata', '??')
                    flight_num = f.get('number', '??')
                    status = f.get('status', 'Unknown')

                    zone = PASSENGER_AIRLINES.get(airline_iata)
                    
                    if zone:
                        all_flights.append({
                            'time': dt,
                            'type': type_label.capitalize(), 
                            'status': status,
                            'zone': zone,
                            'airline': airline_name,
                            'flight_num': flight_num
                        })
                except Exception as parse_e:
                    logging.error(f"Error parsing individual flight: {parse_e}")
                    continue

        except requests.exceptions.HTTPError as http_err:
            # Report the exact HTTP status code back to the logs
            logging.error(f"HTTP Error Encountered (Status {http_err.response.status_code}): Check RapidAPI Key/Subscription!")
            return None 
            
        except Exception as e:
            logging.error(f"API Request Failed for {type_label}: {e}")
            return None

    if not all_flights:
        return pd.DataFrame()
        
    df = pd.DataFrame(all_flights)
    df['hour'] = df['time'].dt.hour
    return df
