import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta, date

import pytz
import cloudinary
import cloudinary.uploader
from flask import Flask, request
from twilio.rest import Client
from apscheduler.schedulers.background import BackgroundScheduler

from image_generator import generate_daily_recap, generate_weekly_recap, calculate_points

app = Flask(__name__)

ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")
CLOUDINARY_URL = os.environ.get("CLOUDINARY_URL")

EASTERN = pytz.timezone("America/New_York")
CHALLENGE_START = date(2025, 5, 1)

DB_PATH = "/data/pushups.db"
PEOPLE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "people.txt")

os.makedirs("/data", exist_ok=True)


# --------------------------------------------------------------------------
# People
# --------------------------------------------------------------------------
def normalize_phone(phone):
    return re.sub(r"[^\d+]", "", phone or "")


def load_people():
    """Parse people.txt into (members, moderators).

    Each list holds dicts: {"name": str, "phone": str}. Lines starting with #
    are comments and blank lines are ignored. A person may appear in both
    sections. Re-read on every call so file edits take effect without a
    redeploy.
    """
    members, moderators = [], []
    section = None
    try:
        with open(PEOPLE_FILE) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                upper = line.upper()
                if upper == "[MEMBERS]":
                    section = "members"
                    continue
                if upper == "[MODERATORS]":
                    section = "moderators"
                    continue
                if "|" not in line or section is None:
                    continue
                name, phone = line.split("|", 1)
                entry = {"name": name.strip(), "phone": normalize_phone(phone)}
                if not entry["name"] or not entry["phone"]:
                    continue
                if section == "members":
                    members.append(entry)
                else:
                    moderators.append(entry)
    except FileNotFoundError:
        print(f"people.txt not found at {PEOPLE_FILE}")
    return members, moderators


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            reps INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            UNIQUE(phone, date)
        )
        """
    )
    conn.commit()
    conn.close()


def upsert_log(phone, name, log_date, reps):
    """One entry per person per day; texting again the same day overwrites."""
    conn = get_db()
    conn.execute(
        """
        INSERT INTO logs (phone, name, date, reps, timestamp)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(phone, date) DO UPDATE SET
            reps = excluded.reps,
            name = excluded.name,
            timestamp = excluded.timestamp
        """,
        (phone, name, log_date.isoformat(), reps, now_eastern().isoformat()),
    )
    conn.commit()
    conn.close()


def daily_logs_for(members, target_date):
    by_phone = {m["phone"]: m["name"] for m in members}
    conn = get_db()
    rows = conn.execute(
        "SELECT phone, reps FROM logs WHERE date = ?", (target_date.isoformat(),)
    ).fetchall()
    conn.close()
    logs = {}
    for row in rows:
        name = by_phone.get(normalize_phone(row["phone"]))
        if name:
            logs[name] = row["reps"]
    return logs


def weekly_logs_for(members, week_start, week_end):
    by_phone = {m["phone"]: m["name"] for m in members}
    conn = get_db()
    rows = conn.execute(
        "SELECT phone, reps FROM logs WHERE date >= ? AND date <= ?",
        (week_start.isoformat(), week_end.isoformat()),
    ).fetchall()
    conn.close()
    logs = {}
    for row in rows:
        name = by_phone.get(normalize_phone(row["phone"]))
        if not name:
            continue
        entry = logs.setdefault(name, {"reps": 0, "days": 0})
        entry["reps"] += row["reps"]
        entry["days"] += 1
    return logs


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def now_eastern():
    return datetime.now(EASTERN)


def extract_reps(body):
    match = re.search(r"\d+", body)
    return int(match.group()) if match else None


# --------------------------------------------------------------------------
# Report generation + delivery
# --------------------------------------------------------------------------
def send_mms_to_moderators(image_path, moderators):
    cloudinary.config(cloudinary_url=CLOUDINARY_URL)
    result = cloudinary.uploader.upload(image_path, resource_type="image", format="png")
    image_url = result["secure_url"]
    print(f"Uploaded recap image: {image_url}")

    client = Client(ACCOUNT_SID, AUTH_TOKEN)
    for mod in moderators:
        try:
            msg = client.messages.create(
                to=mod["phone"], from_=TWILIO_NUMBER, media_url=[image_url]
            )
            print(f"Sent recap to {mod['phone']}: {msg.sid}")
        except Exception as e:
            print(f"Failed to send recap to {mod['phone']}: {e}")


def send_daily_report():
    try:
        members, moderators = load_people()
        if not moderators:
            print("No moderators configured; skipping daily report")
            return
        target_date = now_eastern().date()
        day_number = (target_date - CHALLENGE_START).days + 1
        logs = daily_logs_for(members, target_date)
        img = generate_daily_recap(members, logs, target_date, day_number)
        path = "/tmp/recap_daily.png"
        img.save(path)
        send_mms_to_moderators(path, moderators)
    except Exception as e:
        print(f"send_daily_report failed: {e}")


def send_weekly_report(week_start=None, week_end=None):
    try:
        members, moderators = load_people()
        if not moderators:
            print("No moderators configured; skipping weekly report")
            return
        if week_start is None or week_end is None:
            today = now_eastern().date()
            week_start = today - timedelta(days=today.weekday())
            week_end = today
        week_number = ((week_start - CHALLENGE_START).days // 7) + 1
        logs = weekly_logs_for(members, week_start, week_end)
        img = generate_weekly_recap(members, logs, week_number, week_start, week_end)
        path = "/tmp/recap_weekly.png"
        img.save(path)
        send_mms_to_moderators(path, moderators)
    except Exception as e:
        print(f"send_weekly_report failed: {e}")


def scheduled_weekly_report():
    """Monday 8:50 AM ET: recap the previous complete Mon-Sun week."""
    today = now_eastern().date()
    this_monday = today - timedelta(days=today.weekday())
    send_weekly_report(this_monday - timedelta(days=7), this_monday - timedelta(days=1))


# --------------------------------------------------------------------------
# Admin correction (moderators only)
# --------------------------------------------------------------------------
def handle_admin_correct(body, members):
    # Format: admin correct <firstname> <reps> [MMDD]
    parts = body.split()
    if len(parts) < 4:
        return
    first_name = parts[2].lower()
    try:
        reps = int(parts[3])
    except ValueError:
        return

    target = None
    for m in members:
        if m["name"].split() and m["name"].split()[0].lower() == first_name:
            target = m
            break
    if not target:
        return

    target_date = now_eastern().date()
    if len(parts) >= 5:
        d = parts[4]
        if len(d) != 4 or not d.isdigit():
            return
        try:
            target_date = date(target_date.year, int(d[:2]), int(d[2:]))
        except ValueError:
            return

    upsert_log(target["phone"], target["name"], target_date, reps)
    print(f"Admin correction: {target['name']} -> {reps} reps on {target_date}")


# --------------------------------------------------------------------------
# Webhook
# --------------------------------------------------------------------------
@app.route("/sms", methods=["POST"])
def sms():
    from_number = normalize_phone(request.form.get("From", ""))
    body = (request.form.get("Body", "") or "").strip()
    members, moderators = load_people()

    member_by_phone = {m["phone"]: m for m in members}
    moderator_phones = {m["phone"] for m in moderators}
    is_moderator = from_number in moderator_phones
    text = body.lower()

    if is_moderator:
        if text in ("send daily report", "display daily report"):
            threading.Thread(target=send_daily_report, daemon=True).start()
            return ("", 200)
        if text in ("send weekly report", "display weekly report"):
            threading.Thread(target=send_weekly_report, daemon=True).start()
            return ("", 200)
        if text.startswith("admin correct"):
            handle_admin_correct(body, members)
            return ("", 200)

    member = member_by_phone.get(from_number)
    if member:
        reps = extract_reps(body)
        if reps is not None and reps > 0:
            upsert_log(member["phone"], member["name"], now_eastern().date(), reps)

    # Every other message is silently ignored — no reply, ever.
    return ("", 200)


# --------------------------------------------------------------------------
# Startup
# --------------------------------------------------------------------------
init_db()

scheduler = BackgroundScheduler(timezone=EASTERN)
scheduler.add_job(scheduled_weekly_report, "cron", day_of_week="mon", hour=8, minute=50)
scheduler.start()

if __name__ == "__main__":
    app.run(debug=False, port=5000)
