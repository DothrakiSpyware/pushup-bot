import os
import re
import json
import sqlite3
from datetime import datetime, timedelta, date
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
TIMEZONE = "America/New_York"
CHALLENGE_START = date(2025, 5, 1)

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

def is_test_command(body):
    body = body.strip().lower()
    if re.match(r'^display\s+daily\s+report$', body):
        return "daily"
    if re.match(r'^display\s+weekly\s+report$', body):
        return "weekly"
    return None

def get_date_str(target_date=None):
    tz = pytz.timezone(TIMEZONE)
    if target_date is None:
        target_date = datetime.now(tz).date()
    return target_date.strftime("%Y-%m-%d")

def already_logged_today(phone):
    conn = get_db()
    today = get_date_str()
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
        (phone, reps, now.isoformat(), get_date_str())
    )
    conn.commit()
    conn.close()

def send_image_to_group(image_path):
    client = Client(ACCOUNT_SID, AUTH_TOKEN)
    filename = os.path.basename(image_path)
    image_url = f"{PUBLIC_URL}/recap-image/{filename}"
    
    for number in GROUP_NUMBERS:
        number = number.strip()
        if number:
            client.messages.create(
                from_=TWILIO_NUMBER,
                to=number,
                body="",
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

    test_type = is_test_command(body)
    if test_type == "daily":
        run_daily_recap(is_test=True)
        return "", 204
    if test_type == "weekly":
        run_weekly_recap(is_test=True)
        return "", 204

    reps = parse_reps(body)
    if reps is None:
        return "", 204

    if already_logged_today(from_number):
        return "", 204

    save_log(from_number, reps)
    return "", 204

def get_entries_for_date(target_date_str):
    conn = get_db()
    tz = pytz.timezone(TIMEZONE)
    rows = conn.execute(
        "SELECT phone, reps, logged_at FROM logs WHERE date=? ORDER BY reps DESC",
        (target_date_str,)
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

def run_daily_recap(is_test=False):
    os.makedirs("recap_images", exist_ok=True)
    people = load_people()
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)

    if is_test:
        target_date = now.date()
        target_date_str = get_date_str(target_date)
        date_str = now.strftime("%A, %B %-d") + " (test)"
    else:
        target_date = (now - timedelta(days=1)).date()
        target_date_str = get_date_str(target_date)
        date_str = target_date.strftime("%A, %B %-d")

    entries = get_entries_for_date(target_date_str)

    if not entries and not is_test:
        return

    day_num = (target_date - CHALLENGE_START).days + 1

    filename = f"daily_{target_date_str}{'_test' if is_test else ''}.png"
    path = os.path.join("recap_images", filename)
    generate_daily_image(date_str, day_num, entries, people, path)
    send_image_to_group(path)

def run_weekly_recap(is_test=False):
    os.makedirs("recap_images", exist_ok=True)
    people = load_people()
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)

    week_end = now.date()
    week_start = week_end - timedelta(days=6)
    week_start_str = get_date_str(week_start)
    week_end_str = get_date_str(week_end)

    conn = get_db()
    rows = conn.execute(
        "SELECT phone, reps, date FROM logs WHERE date >= ? AND date <= ?",
        (week_start_str, week_end_str)
    ).fetchall()
    conn.close()

    weekly_data = {}
    for phone in people:
        weekly_data[phone] = {
            "total_pts": 0,
            "total_reps": 0,
            "days_logged": 0,
            "best_day": 0
        }

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

    week_num = ((week_end - CHALLENGE_START).days // 7) + 1
    date_range = f"{week_start.strftime('%b %-d')} – {week_end.strftime('%b %-d')}"
    suffix = " (test)" if is_test else ""

    filename = f"weekly_{week_end_str}{'_test' if is_test else ''}.png"
    path = os.path.join("recap_images", filename)
    generate_weekly_image(week_num, date_range + suffix, weekly_data, people, path)
    send_image_to_group(path)

scheduler = BackgroundScheduler(timezone=TIMEZONE)
scheduler.add_job(run_daily_recap, "cron", hour=9, minute=0)
scheduler.add_job(run_weekly_recap, "cron", day_of_week="mon", hour=9, minute=0)
scheduler.start()

init_db()

if __name__ == "__main__":
    app.run(debug=False, port=5000)
