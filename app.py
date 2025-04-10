from flask import Flask, request, render_template
import sqlite3
from datetime import datetime
import threading
import time
import random
import os
import math
import smtplib
from email.mime.text import MIMEText
import logging

app = Flask(__name__)

# File paths
DB_FILE = "stolen_vehicles.db"
DETECTIONS_FILE = "detections.txt"
ALERTS_FILE = "alerts.txt"
LOG_FILE = "app.log"

# Mock police stations (lat, long, email)
POLICE_STATIONS = {
    "Amritsar Central": {"coords": (31.6340, 74.8723), "email": "amritsar.police@example.com"},
    "Ludhiana North": {"coords": (30.9010, 75.8573), "email": "ludhiana.police@example.com"},
    "Jalandhar West": {"coords": (31.3260, 75.5762), "email": "jalandhar.police@example.com"}
}

# Email config from environment variables
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "your.email@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "your_app_password")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT", "your.email@gmail.com")

# Logging setup
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Initialize database
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS vehicles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        number_plate TEXT UNIQUE,
        owner_name TEXT,
        report_date TEXT,
        description TEXT,
        model TEXT DEFAULT 'Unknown',
        color TEXT DEFAULT 'Unknown'
    )''')
    conn.commit()
    conn.close()

# Mock challan sighting (for now)
def generate_mock_sighting():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT number_plate FROM vehicles")
    plates = c.fetchall()
    conn.close()
    if random.random() < 0.2 and plates:
        number = random.choice(plates)[0]
    else:
        number = f"PB{random.randint(1, 99):02d}{chr(random.randint(65, 90))}{chr(random.randint(65, 90))}{random.randint(1000, 9999)}"
    lat = random.uniform(30.5, 32.0)
    lon = random.uniform(74.5, 76.5)
    direction = random.choice(["North", "South", "East", "West"])
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {"vehicle": number, "location": (lat, lon), "time": timestamp, "direction": direction}

# Haversine distance
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

# Nearest police station
def find_nearest_station(location):
    min_distance = float("inf")
    nearest_station = None
    for station, data in POLICE_STATIONS.items():
        distance = calculate_distance(location[0], location[1], data["coords"][0], data["coords"][1])
        if distance < min_distance:
            min_distance = distance
            nearest_station = station
    return nearest_station, min_distance

# Predict next location
def predict_next_location(current_location, direction):
    lat, lon = current_location
    if direction == "North":
        lat += 0.09
    elif direction == "South":
        lat -= 0.09
    elif direction == "East":
        lon += 0.09
    elif direction == "West":
        lon -= 0.09
    return (lat, lon)

# Send email alert
def send_alert_email(number_plate, owner_name, sighting, nearest_station, model, color):
    next_location = predict_next_location(sighting["location"], sighting["direction"])
    body = (
        f"Stolen Vehicle Alert!\n"
        f"Number Plate: {number_plate}\n"
        f"Owner: {owner_name}\n"
        f"Model: {model}\n"
        f"Color: {color}\n"
        f"Time: {sighting['time']}\n"
        f"Location: ({sighting['location'][0]:.4f}, {sighting['location'][1]:.4f})\n"
        f"Heading: {sighting['direction']}\n"
        f"Nearest Station: {nearest_station} ({calculate_distance(sighting['location'][0], sighting['location'][1], POLICE_STATIONS[nearest_station]['coords'][0], POLICE_STATIONS[nearest_station]['coords'][1]):.2f} km)\n"
        f"Predicted Next Location: ({next_location[0]:.4f}, {next_location[1]:.4f})\n"
    )
    msg = MIMEText(body)
    msg["Subject"] = f"Stolen Vehicle Alert: {number_plate}"
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECIPIENT

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())
        logging.info(f"Email alert sent for {number_plate}")
    except Exception as e:
        logging.error(f"Email failed for {number_plate}: {e}")

# Background sighting check
def check_sightings():
    while True:
        try:
            sighting = generate_mock_sighting()
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT number_plate, owner_name, model, color FROM vehicles WHERE number_plate = ?", (sighting["vehicle"],))
            result = c.fetchone()
            conn.close()

            if result:
                number_plate, owner_name, model, color = result
                nearest_station, distance = find_nearest_station(sighting["location"])
                detection = (
                    f"DETECTION: Stolen vehicle {number_plate} spotted!\n"
                    f"Owner: {owner_name}\n"
                    f"Model: {model}\n"
                    f"Color: {color}\n"
                    f"Time: {sighting['time']}\n"
                    f"Location: ({sighting['location'][0]:.4f}, {sighting['location'][1]:.4f})\n"
                    f"Heading: {sighting['direction']}\n"
                    f"Nearest Station: {nearest_station} ({distance:.2f} km)"
                )
                with open(DETECTIONS_FILE, "a") as f:
                    f.write(detection + "\n")

                next_location = predict_next_location(sighting["location"], sighting["direction"])
                alert = (
                    f"ALERT SENT: Stolen vehicle {number_plate}\n"
                    f"Time: {sighting['time']}\n"
                    f"Location: ({sighting['location'][0]:.4f}, {sighting['location'][1]:.4f})\n"
                    f"Heading: {sighting['direction']}\n"
                    f"Nearest Station: {nearest_station}\n"
                    f"Predicted Next Location: ({next_location[0]:.4f}, {next_location[1]:.4f})"
                )
                with open(ALERTS_FILE, "a") as f:
                    f.write(alert + "\n")
                send_alert_email(number_plate, owner_name, sighting, nearest_station, model, color)
            time.sleep(5)
        except Exception as e:
            logging.error(f"Sighting check failed: {e}")
            time.sleep(5)

# Home page
@app.route("/", methods=["GET", "POST"])
def home():
    init_db()
    message = ""
    if request.method == "POST":
        number_plate = request.form["number_plate"].upper()
        owner_name = request.form["owner_name"]
        description = request.form["description"]
        model = request.form.get("model", "Unknown")
        color = request.form.get("color", "Unknown")
        report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("INSERT INTO vehicles (number_plate, owner_name, report_date, description, model, color) VALUES (?, ?, ?, ?, ?, ?)",
                      (number_plate, owner_name, report_date, description, model, color))
            conn.commit()
            message = f"Vehicle {number_plate} reported successfully!"
            logging.info(f"Vehicle reported: {number_plate}")
        except sqlite3.IntegrityError:
            message = f"Error: Vehicle {number_plate} already reported."
            logging.warning(f"Duplicate report attempt: {number_plate}")
        finally:
            conn.close()

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT number_plate, owner_name, report_date, description, model, color FROM vehicles")
    vehicles = c.fetchall()
    conn.close()
    return render_template("index.html", vehicles=vehicles, message=message)

# Detections page
@app.route("/detections")
def detections():
    detections = []
    alerts = []
    if os.path.exists(DETECTIONS_FILE):
        with open(DETECTIONS_FILE, "r") as f:
            content = f.read().strip().split("\n\n")
            detections = [d.strip() for d in content if d.strip()]
    if os.path.exists(ALERTS_FILE):
        with open(ALERTS_FILE, "r") as f:
            content = f.read().strip().split("\n\n")
            alerts = [a.strip() for a in content if a.strip()]
    return render_template("detections.html", detections=detections, alerts=alerts)

# Start background thread
threading.Thread(target=check_sightings, daemon=True).start()

if __name__ == "__main__":
    for f in [DETECTIONS_FILE, ALERTS_FILE, LOG_FILE]:
        if os.path.exists(f):
            os.remove(f)
    port = int(os.getenv("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)