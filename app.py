import os
import re
import json
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, request
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from apscheduler.schedulers.background import BackgroundScheduler
from image_generator import generate_daily_image, generate_weekly_image, score_from_reps
import pytz

app = Flask(__name__)

ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")
GROUP_NUMBERS = os.environ.get("GROUP_NUMBERS", "").split(",")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "")
TIMEZONE = os.environ.get("TIMEZONE", "America/New_York")

DB_PATH = "pushups.db"

def load_people():
    with open("people.json") as f:
        return json.load(f)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            reps INTEGER NOT NULL,
            logged_at TEXT NOT NULL,
            date TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def parse_reps(body):
    body = body.strip()
    patterns = [
        r'^\s*(\d+)\s*$',
        r'(\d+)\s*push\s*ups?',
        r'(\d+)\s*push\s*ups?\s*done',
        r'just\s*did\s*(\d+)',
        r'did\s*(\d+)',
        r'done\s*(\d+)',
        r'(\d+)\s*done',
        r'(\d+)\s*reps?',
        r'(\d+)\s*today',
        r'today\s*(\d+)',
        r'(\d+)\s*complete',
        r'complete[d]?\s*(\d+)',
        r'knocked\s*out\s*(\d+)',
        r'finished\s*(\d+)',
        r'(\d+)\s*finished',
        r'got\s*(\d+)',
        r'(\d+)\s*got\s*it',
        r'logging\s*(\d+)',
        r'log\s*(\d+)',
        r'(\d+)\s*logged',
        r'(\d+)\s*for\s*today',
    ]
    for pattern in patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            val = int(match.group(1))
            if 1 <= val <= 2000:
                return val
    return None

def get_today_str():
    tz = pytz.timezone(TIMEZONE)
    return datetime.now(tz).strftime("%Y-%m-%d")

def already_logged_today(phone):
    conn = get_db()
    today = get_today_str()
    row = conn.execute(
        "SELECT id FROM logs WHERE phone=? AND date=?", (phone, today)
    ).fetchone()
    conn.close()
    return row is not None

def save_log(phone, reps):
    conn = get_db()
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    conn.execute(
        "INSERT INTO logs (phone, reps, logged_at, date) VALUES (?, ?, ?, ?)",
        (phone, reps, now.isoformat(), get_today_str())
    )
    conn.commit()
    conn.close()

def send_image_to_group(image_path):
    client = Client(ACCOUNT_SID, AUTH_TOKEN)
    image_url = f"{PUBLIC_URL}/recap-image/{os.path.basename(image_path)}"
    for number in GROUP_NUMBERS:
        number = number.strip()
        if number:
            client.messages.create(
                from_=TWILIO_NUMBER,
                to=number,
                media_url=[image_url]
            )

@app.route("/recap-image/<filename>")
def serve_image(filename):
    from flask import send_from_directory
    return send_from_directory("recap_images", filename)

@app.route("/sms", methods=["POST"])
def sms_reply():
    from_number = request.form.get("From", "")
    body = request.form.get("Body", "")
    people = load_people()

    if from_number not in people:
        return "", 204

    reps = parse_reps(body)

    if reps is None:
        return "", 204

    if already_logged_today(from_number):
        conn = get_db()
        today = get_today_str()
        row = conn.execute(
            "SELECT reps FROM logs WHERE phone=? AND date=? ORDER BY id DESC LIMIT 1",
            (from_number, today)
        ).fetchone()
        conn.close()
        return "", 204

    save_log(from_number, reps)
    return "", 204

def get_todays_entries():
    conn = get_db()
    today = get_today_str()
    tz = pytz.timezone(TIMEZONE)
    rows = conn.execute(
        "SELECT phone, reps, logged_at FROM logs WHERE date=? ORDER BY reps DESC",
        (today,)
    ).fetchall()
    conn.close()
    entries = []
    for row in rows:
        logged_at = datetime.fromisoformat(row["logged_at"])
        entries.append({
            "phone": row["phone"],
            "reps": row["reps"],
            "time_str": logged_at.strftime("%-I:%M%p").lower()
        })
    return entries

def send_daily_recap():
    os.makedirs("recap_images", exist_ok=True)
    people = load_people()
    entries = get_todays_entries()

    if not entries:
        return

    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    date_str = now.strftime("%A, %B %-d")

    from datetime import date
    challenge_start = date(2025, 5, 1)
    day_num = (date.today() - challenge_start).days + 1

    filename = f"daily_{get_today_str()}.png"
    path = os.path.join("recap_images", filename)
    generate_daily_image(date_str, day_num, entries, people, path)
    send_image_to_group(path)

def send_weekly_recap():
    os.makedirs("recap_images", exist_ok=True)
    people = load_people()
    conn = get_db()
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    week_start = (now - timedelta(days=6)).strftime("%Y-%m-%d")
    today = get_today_str()

    rows = conn.execute(
        "SELECT phone, reps, date FROM logs WHERE date >= ? AND date <= ?",
        (week_start, today)
    ).fetchall()
    conn.close()

    weekly_data = {}
    for phone in people:
        weekly_data[phone] = {"total_pts": 0, "total_reps": 0, "days_logged": 0, "best_day": 0}

    for row in rows:
        phone = row["phone"]
        if phone not in weekly_data:
            continue
        reps = row["reps"]
        pts = score_from_reps(reps)
        weekly_data[phone]["total_pts"] += pts
        weekly_data[phone]["total_reps"] += reps
        weekly_data[phone]["days_logged"] += 1
        if reps > weekly_data[phone]["best_day"]:
            weekly_data[phone]["best_day"] = reps

    from datetime import date
    week_num = ((date.today() - date(2025, 5, 1)).days // 7) + 1
    date_range = f"{(now - timedelta(days=6)).strftime('%b %-d')} – {now.strftime('%b %-d')}"

    filename = f"weekly_{today}.png"
    path = os.path.join("recap_images", filename)
    generate_weekly_image(week_num, date_range, weekly_data, people, path)
    send_image_to_group(path)

scheduler = BackgroundScheduler(timezone=TIMEZONE)
scheduler.add_job(send_daily_recap, "cron", hour=22, minute=0)
scheduler.add_job(send_weekly_recap, "cron", day_of_week="sun", hour=21, minute=0)
scheduler.start()

init_db()

if __name__ == "__main__":
    app.run(debug=False, port=5000)
