from flask import Flask, request, render_template, redirect, url_for, flash, session
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
import json
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.urandom(24)

# File paths
DB_FILE = "/tmp/stolen_vehicles.db"
DETECTIONS_FILE = "/tmp/detections.txt"
ALERTS_FILE = "/tmp/alerts.txt"
LOG_FILE = "/tmp/app.log"
STATIONS_FILE = "/tmp/police_stations.json"
ANPR_FEED = "static/anpr_feed.json"
UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Ensure upload folder exists
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# Logging setup
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Email config
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "your.email@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "your_app_password")

# Load police stations
def load_police_stations():
    try:
        if os.path.exists(STATIONS_FILE):
            with open(STATIONS_FILE, "r") as f:
                return json.load(f)
        else:
            default_stations = {
                "Amritsar Central": {"coords": (31.6340, 74.8723), "email": "amritsar.police@example.com"},
                "Ludhiana North": {"coords": (30.9010, 75.8573), "email": "ludhiana.police@example.com"},
                "Jalandhar West": {"coords": (31.3260, 75.5762), "email": "jalandhar.police@example.com"}
            }
            with open(STATIONS_FILE, "w") as f:
                json.dump(default_stations, f)
            return default_stations
    except Exception as e:
        logging.error(f"Failed to load police stations: {e}")
        return {}

POLICE_STATIONS = load_police_stations()

# Initialize database
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT UNIQUE,
        email TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS vehicles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        number_plate TEXT UNIQUE,
        owner_name TEXT,
        report_date TEXT,
        description TEXT,
        model TEXT,
        color TEXT,
        rc_path TEXT,
        fir_path TEXT,
        lat REAL,
        lon REAL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id INTEGER,
        station_name TEXT,
        time TEXT,
        lat REAL,
        lon REAL,
        direction TEXT,
        status TEXT DEFAULT 'Pending',
        FOREIGN KEY(vehicle_id) REFERENCES vehicles(id)
    )''')
    conn.commit()
    conn.close()

# Generate OTP
def generate_otp():
    return str(random.randint(100000, 999999))

# Send OTP email
def send_otp_email(email, otp):
    body = f"Your OTP for Stolen Vehicle Portal is: {otp}\nValid for 5 minutes."
    msg = MIMEText(body)
    msg["Subject"] = "Your OTP Code"
    msg["From"] = EMAIL_SENDER
    msg["To"] = email
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, email, msg.as_string())
        logging.info(f"OTP sent to {email}")
    except Exception as e:
        logging.error(f"OTP email failed for {email}: {e}")

# Mock ANPR feed
def generate_mock_anpr_feed():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT number_plate FROM vehicles")
    plates = c.fetchall()
    conn.close()
    feed = []
    for _ in range(5):
        if random.random() < 0.4 and plates:
            number = random.choice(plates)[0]
        else:
            number = f"PB{random.randint(1, 99):02d}{chr(random.randint(65, 90))}{chr(random.randint(65, 90))}{random.randint(1000, 9999)}"
        feed.append({
            "number_plate": number,
            "lat": random.uniform(30.5, 32.0),
            "lon": random.uniform(74.5, 76.5),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "direction": random.choice(["North", "South", "East", "West"])
        })
    with open(ANPR_FEED, "w") as f:
        json.dump(feed, f)

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
def find_nearest_station(lat, lon):
    min_distance = float("inf")
    nearest_station = None
    for station, data in POLICE_STATIONS.items():
        distance = calculate_distance(lat, lon, data["coords"][0], data["coords"][1])
        if distance < min_distance:
            min_distance = distance
            nearest_station = station
    return nearest_station, min_distance

# Predict next location
def predict_next_location(lat, lon, direction):
    if direction == "North":
        lat += 0.09
    elif direction == "South":
        lat -= 0.09
    elif direction == "East":
        lon += 0.09
    elif direction == "West":
        lon -= 0.09
    return lat, lon

# Send alert email
def send_alert_email(vehicle, sighting, nearest_station):
    next_lat, next_lon = predict_next_location(sighting["lat"], sighting["lon"], sighting["direction"])
    body = (
        f"Stolen Vehicle Alert!\n"
        f"Number Plate: {vehicle['number_plate']}\n"
        f"Owner: {vehicle['owner_name']}\n"
        f"Model: {vehicle['model']}\n"
        f"Color: {vehicle['color']}\n"
        f"Time: {sighting['time']}\n"
        f"Location: ({sighting['lat']:.4f}, {sighting['lon']:.4f})\n"
        f"Heading: {sighting['direction']}\n"
        f"Nearest Station: {nearest_station} ({calculate_distance(sighting['lat'], sighting['lon'], POLICE_STATIONS[nearest_station]['coords'][0], POLICE_STATIONS[nearest_station]['coords'][1]):.2f} km)\n"
        f"Predicted Next Location: ({next_lat:.4f}, {next_lon:.4f})\n"
        f"Documents: {vehicle['rc_path'] or 'None'}, {vehicle['fir_path'] or 'None'}\n"
    )
    msg = MIMEText(body)
    msg["Subject"] = f"Stolen Vehicle Alert: {vehicle['number_plate']}"
    msg["From"] = EMAIL_SENDER
    msg["To"] = POLICE_STATIONS[nearest_station]["email"]
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, POLICE_STATIONS[nearest_station]["email"], msg.as_string())
        logging.info(f"Alert sent for {vehicle['number_plate']} to {nearest_station}")
    except Exception as e:
        logging.error(f"Alert email failed for {vehicle['number_plate']}: {e}")

# Background ANPR check
def check_anpr_feed():
    while True:
        try:
            generate_mock_anpr_feed()
            with open(ANPR_FEED, "r") as f:
                sightings = json.load(f)
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            for sighting in sightings:
                c.execute("SELECT id, number_plate, owner_name, model, color, rc_path, fir_path FROM vehicles WHERE number_plate = ?", (sighting["number_plate"],))
                vehicle = c.fetchone()
                if vehicle:
                    vehicle_id, number_plate, owner_name, model, color, rc_path, fir_path = vehicle
                    nearest_station, distance = find_nearest_station(sighting["lat"], sighting["lon"])
                    detection = (
                        f"DETECTION: Stolen vehicle {number_plate} spotted!\n"
                        f"Owner: {owner_name}\n"
                        f"Model: {model}\n"
                        f"Color: {color}\n"
                        f"Time: {sighting['time']}\n"
                        f"Location: ({sighting['lat']:.4f}, {sighting['lon']:.4f})\n"
                        f"Heading: {sighting['direction']}\n"
                        f"Nearest Station: {nearest_station} ({distance:.2f} km)"
                    )
                    with open(DETECTIONS_FILE, "a") as f:
                        f.write(detection + "\n")
                    c.execute("INSERT INTO alerts (vehicle_id, station_name, time, lat, lon, direction) VALUES (?, ?, ?, ?, ?, ?)",
                              (vehicle_id, nearest_station, sighting["time"], sighting["lat"], sighting["lon"], sighting["direction"]))
                    conn.commit()
                    send_alert_email({
                        "number_plate": number_plate,
                        "owner_name": owner_name,
                        "model": model,
                        "color": color,
                        "rc_path": rc_path,
                        "fir_path": fir_path
                    }, sighting, nearest_station)
            conn.close()
            time.sleep(10)
        except Exception as e:
            logging.error(f"ANPR check failed: {e}")
            time.sleep(10)

# Verify OTP
@app.route("/verify", methods=["GET", "POST"])
def verify():
    if "phone" not in session or "otp" not in session:
        return redirect(url_for("home"))
    if request.method == "POST":
        user_otp = request.form["otp"]
        if user_otp == session["otp"] and time.time() < session["otp_expiry"]:
            phone = session["phone"]
            email = session["email"]
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO users (phone, email) VALUES (?, ?)", (phone, email))
            conn.commit()
            c.execute("SELECT id FROM users WHERE phone = ?", (phone,))
            user_id = c.fetchone()[0]
            conn.close()
            session["user_id"] = user_id
            session.pop("otp", None)
            session.pop("otp_expiry", None)
            flash("Verification successful!")
            return redirect(url_for("home"))
        flash("Invalid or expired OTP.")
    return render_template("verify.html")

# Home page (handles login and vehicle reporting)
@app.route("/", methods=["GET", "POST"])
def home():
    init_db()
    if "user_id" in session:
        # Logged in
        message = ""
        if request.method == "POST" and "number_plate" in request.form:
            number_plate = request.form["number_plate"].upper()
            owner_name = request.form["owner_name"]
            description = request.form["description"]
            model = request.form.get("model", "Unknown")
            color = request.form.get("color", "Unknown")
            lat = float(request.form["lat"]) if request.form["lat"] else None
            lon = float(request.form["lon"]) if request.form["lon"] else None
            rc_file = request.files.get("rc")
            fir_file = request.files.get("fir")
            rc_path = fir_path = None

            if rc_file and rc_file.filename.split(".")[-1].lower() in ALLOWED_EXTENSIONS:
                rc_filename = secure_filename(f"{number_plate}_rc_{int(time.time())}.{rc_file.filename.split('.')[-1]}")
                rc_path = os.path.join(app.config["UPLOAD_FOLDER"], rc_filename)
                rc_file.save(rc_path)
            if fir_file and fir_file.filename.split(".")[-1].lower() in ALLOWED_EXTENSIONS:
                fir_filename = secure_filename(f"{number_plate}_fir_{int(time.time())}.{fir_file.filename.split('.')[-1]}")
                fir_path = os.path.join(app.config["UPLOAD_FOLDER"], fir_filename)
                fir_file.save(fir_path)

            try:
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("INSERT INTO vehicles (user_id, number_plate, owner_name, report_date, description, model, color, rc_path, fir_path, lat, lon) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (session["user_id"], number_plate, owner_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), description, model, color, rc_path, fir_path, lat, lon))
                conn.commit()
                message = f"Vehicle {number_plate} reported successfully!"
                logging.info(f"Vehicle reported: {number_plate} by user {session['phone']}")
            except sqlite3.IntegrityError:
                message = f"Error: Vehicle {number_plate} already reported."
            except Exception as e:
                message = f"Error: {e}"
            finally:
                conn.close()

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT number_plate, owner_name, report_date, description, model, color, rc_path, fir_path, lat, lon FROM vehicles WHERE user_id = ?", (session["user_id"],))
        vehicles = c.fetchall()
        c.execute("SELECT v.number_plate, a.time, a.lat, a.lon, a.direction, a.station_name FROM alerts a JOIN vehicles v ON a.vehicle_id = v.id WHERE v.user_id = ?", (session["user_id"],))
        sightings = c.fetchall()
        conn.close()
        return render_template("index.html", vehicles=vehicles, sightings=sightings, message=message, logged_in=True)

    # Not logged in
    if request.method == "POST":
        phone = request.form["phone"]
        email = request.form["email"]
        otp = generate_otp()
        session["phone"] = phone
        session["email"] = email
        session["otp"] = otp
        session["otp_expiry"] = time.time() + 300  # 5 minutes
        send_otp_email(email, otp)
        flash("OTP sent to your email.")
        return redirect(url_for("verify"))
    return render_template("index.html", logged_in=False)

# Police panel
@app.route("/police", methods=["GET", "POST"])
def police():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if request.method == "POST":
        alert_id = request.form["alert_id"]
        status = request.form["status"]
        c.execute("UPDATE alerts SET status = ? WHERE id = ?", (status, alert_id))
        conn.commit()
    c.execute("SELECT a.id, v.number_plate, v.owner_name, v.model, v.color, a.time, a.lat, a.lon, a.direction, a.station_name, a.status, v.rc_path, v.fir_path FROM alerts a JOIN vehicles v ON a.vehicle_id = v.id")
    alerts = c.fetchall()
    conn.close()
    return render_template("police.html", alerts=alerts)

# Admin panel
@app.route("/admin")
def admin():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, phone, email FROM users")
    users = c.fetchall()
    c.execute("SELECT id, number_plate, owner_name, model, color, report_date FROM vehicles")
    vehicles = c.fetchall()
    c.execute("SELECT a.id, v.number_plate, a.station_name, a.time, a.status FROM alerts a JOIN vehicles v ON a.vehicle_id = v.id")
    alerts = c.fetchall()
    c.execute("SELECT station_name, COUNT(*) as alert_count FROM alerts GROUP BY station_name")
    analytics = c.fetchall()
    conn.close()
    return render_template("admin.html", users=users, vehicles=vehicles, alerts=alerts, analytics=analytics, police_stations=POLICE_STATIONS)

# Status page
@app.route("/status")
def status():
    status_info = {
        "database": "OK" if os.path.exists(DB_FILE) else "Not Found",
        "detections_file": "OK" if os.path.exists(DETECTIONS_FILE) else "Not Found",
        "alerts_file": "OK" if os.path.exists(ALERTS_FILE) else "Not Found",
        "police_stations": "OK" if POLICE_STATIONS else "Not Loaded",
        "email_config": "OK" if EMAIL_SENDER and EMAIL_PASSWORD else "Missing Variables",
        "last_log": "None"
    }
    try:
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
            status_info["last_log"] = lines[-1].strip() if lines else "No logs yet"
    except Exception as e:
        status_info["last_log"] = f"Error reading logs: {e}"
    return render_template("status.html", status=status_info)

# Start background thread
threading.Thread(target=check_anpr_feed, daemon=True).start()

if __name__ == "__main__":
    for f in [DETECTIONS_FILE, ALERTS_FILE, LOG_FILE, STATIONS_FILE, ANPR_FEED]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except:
                pass
    init_db()
    port = int(os.getenv("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port = int(os.getenv("PORT", 5000)))