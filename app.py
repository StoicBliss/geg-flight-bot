import os
import json
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
import pytz

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("Set TELEGRAM_TOKEN environment variable")

# URL to scrape
GEG_URL = "https://spokaneairports.net/flights/"

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

def fetch_departures():
    """
    Scrape Spokane Airport flights page and extract departures list from the __NEXT_DATA__ JSON blob.
    Returns a list of flight dicts or None.
    """
    try:
        r = requests.get(GEG_URL, timeout=15)
        r.raise_for_status()
    except Exception as e:
        app.logger.error("Failed to fetch GEG page: %s", e)
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # Next.js sites embed a JSON blob in a script tag with id="__NEXT_DATA__"
    script = soup.find("script", id="__NEXT_DATA__")
    if not script:
        app.logger.error("__NEXT_DATA__ script not found")
        return None

    try:
        data = json.loads(script.string)
    except Exception as e:
        app.logger.error("Failed to parse __NEXT_DATA__ JSON: %s", e)
        return None

    # Try common paths for departures. This may vary over time.
    flights = None
    # Defensive navigation through possible keys
    try:
        # common pattern: props.pageProps.departures.flights
        flights = data.get("props", {}).get("pageProps", {}).get("departures", {}).get("flights")
    except Exception:
        flights = None

    if not flights:
        # fallback: try to search the JSON for keys named "departures" containing "flights"
        def search_for_key(obj, keyname):
            if isinstance(obj, dict):
                if keyname in obj:
                    return obj[keyname]
                for v in obj.values():
                    res = search_for_key(v, keyname)
                    if res:
                        return res
            elif isinstance(obj, list):
                for item in obj:
                    res = search_for_key(item, keyname)
                    if res:
                        return res
            return None

        departures_obj = search_for_key(data, "departures")
        if departures_obj and isinstance(departures_obj, dict):
            flights = departures_obj.get("flights")

    if not flights or not isinstance(flights, list):
        app.logger.error("Could not locate flights list in page JSON")
        return None

    return flights

def group_by_hour(flights):
    """
    Count scheduled departures by local Spokane hour. Returns sorted dict { "HH:00": count }.
    """
    counts = {}
    pacific = pytz.timezone("America/Los_Angeles")

    for f in flights:
        # Many flight objects use keys like 'scheduledTime', 'scheduled', or 'time'
        sched = f.get("scheduledTime") or f.get("scheduled") or f.get("time") or f.get("scheduled_at")
        # Some pages provide nested structures. If sched is dict, try to extract 'utc' or 'iso'
        if isinstance(sched, dict):
            sched = sched.get("utc") or sched.get("iso") or sched.get("value")

        if not sched:
            # try other fields
            sched = f.get("localScheduledTime") or f.get("scheduledLocal")

        if not sched:
            continue

        try:
            # Normalize Z or timezone-less ISO
            if isinstance(sched, str):
                if sched.endswith("Z"):
                    dt = datetime.fromisoformat(sched.replace("Z", "+00:00"))
                else:
                    # try plain ISO then assume UTC
                    dt = datetime.fromisoformat(sched)
            else:
                # if it's numeric or another format, skip
                continue
        except Exception:
            # fallback: try parsing common formats
            try:
                dt = datetime.strptime(str(sched), "%Y-%m-%dT%H:%M:%S%z")
            except Exception:
                continue

        try:
            dt_local = dt.astimezone(pacific)
        except Exception:
            # If no tz info assume UTC then convert
            dt_local = dt.replace(tzinfo=pytz.utc).astimezone(pacific)

        hour_label = dt_local.strftime("%H:00")
        counts[hour_label] = counts.get(hour_label, 0) + 1

    # Ensure sorted by hour ascending
    sorted_counts = dict(sorted(counts.items()))
    return sorted_counts

def format_summary(counts):
    if not counts:
        return "No departures found or could not parse schedule."
    lines = ["GEG departures grouped by hour (Pacific Time):", ""]
    # Show hours 00 to 23 explicitly even if zero to give full-day context
    all_hours = [f"{h:02d}:00" for h in range(24)]
    for h in all_hours:
        c = counts.get(h, 0)
        lines.append(f"{h}  →  {c} flights")
    return "\n".join(lines)

def send_message(chat_id, text, parse_mode="Markdown"):
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        app.logger.error("Failed to send message: %s", e)
        return False

@app.route("/webhook", methods=["POST"])
def webhook_root():
    # Simple health check or bot-level endpoint (not used by Telegram)
    return jsonify({"ok": True, "msg": "use /webhook/<token> for updates"}), 200

@app.route(f"/webhook/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    """
    Telegram will POST updates here. We parse incoming messages and respond to /departures.
    """
    update = request.get_json(force=True, silent=True)
    if not update:
        return jsonify({"ok": False}), 400

    # Support message or callback_query if needed later
    message = update.get("message") or update.get("edited_message")
    if not message:
        return jsonify({"ok": True}), 200

    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip() if message.get("text") else ""

    if not chat_id or not text:
        return jsonify({"ok": True}), 200

    # handle command
    if text.startswith("/departures"):
        send_message(chat_id, "Working. Fetching departures, please wait...")
        flights = fetch_departures()
        if flights is None:
            send_message(chat_id, "Sorry. Could not fetch departure data from GEG.")
            return jsonify({"ok": True}), 200

        summary = group_by_hour(flights)
        message_text = format_summary(summary)
        send_message(chat_id, message_text)
    else:
        send_message(chat_id, "Send /departures to get departures grouped by hour.")

    return jsonify({"ok": True}), 200

# quick health page
@app.route("/health", methods=["GET"])
def health():
    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
