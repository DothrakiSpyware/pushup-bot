import os
import re
import json
import sqlite3
from datetime import datetime, timedelta, date
from flask import Flask, request
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from apscheduler.schedulers.background import BackgroundScheduler
from image_generator import generate_daily_recap, generate_weekly_recap, calculate_points
import pytz

os.makedirs("/data", exist_ok=True)

app = Flask(__name__)

ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")
MESSAGING_SERVICE_SID = os.environ.get("TWILIO_MESSAGING_SERVICE_SID")
ADMIN_NUMBER = os.environ.get("ADMIN_NUMBER", "")
GROUP_NUMBERS = [n.strip() for n in os.environ.get("GROUP_NUMBERS", "").split(",") if n.strip()]
PUBLIC_URL = os.environ.get("PUBLIC_URL", "")
TIMEZONE = "America/New_York"
CHALLENGE_START = date(2025, 5, 1)

DB_PATH = "/data/pushups.db"

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
    import cloudinary
    import cloudinary.uploader
    
    cloudinary.config(cloudinary_url=os.environ.get("CLOUDINARY_URL"))
    
    upload_result = cloudinary.uploader.upload(
        image_path,
        resource_type="image",
        format="png"
    )
    
    image_url = upload_result["secure_url"]
    print(f"Image uploaded to: {image_url}")
    
    client = Client(ACCOUNT_SID, AUTH_TOKEN)

    recipients = [n for n in GROUP_NUMBERS if n and n != TWILIO_NUMBER]
    if not recipients:
        print("No group recipients configured")
        return

    send_kwargs = {
        "to": recipients,
        "body": "",
        "media_url": [image_url],
    }
    if MESSAGING_SERVICE_SID:
        send_kwargs["messaging_service_sid"] = MESSAGING_SERVICE_SID
    else:
        send_kwargs["from_"] = TWILIO_NUMBER

    try:
        msg = client.messages.create(**send_kwargs)
        print(f"Group MMS sent to {recipients}: {getattr(msg, 'sid', '?')}")
    except Exception as e:
        print(f"Group MMS send failed ({e}); falling back to per-recipient send")
        for number in recipients:
            try:
                per = {
                    "to": number,
                    "body": "",
                    "media_url": [image_url],
                }
                if MESSAGING_SERVICE_SID:
                    per["messaging_service_sid"] = MESSAGING_SERVICE_SID
                else:
                    per["from_"] = TWILIO_NUMBER
                msg = client.messages.create(**per)
                print(f"Sent to {number}: {msg.sid}")
            except Exception as e2:
                print(f"Failed to send to {number}: {e2}")

@app.route("/recap-image/<filename>")
def serve_image(filename):
    from flask import send_from_directory
    return send_from_directory("recap_images", filename)

def send_admin_sms(message):
    if not ADMIN_NUMBER:
        return
    try:
        client = Client(ACCOUNT_SID, AUTH_TOKEN)
        kwargs = {"to": ADMIN_NUMBER, "body": message}
        if MESSAGING_SERVICE_SID:
            kwargs["messaging_service_sid"] = MESSAGING_SERVICE_SID
        else:
            kwargs["from_"] = TWILIO_NUMBER
        client.messages.create(**kwargs)
    except Exception as e:
        print(f"Failed admin SMS: {e}")


def handle_admin_correct(body):
    parts = body.strip().split()
    # ["admin", "correct", first_name, reps, optional_date]
    if len(parts) < 4:
        send_admin_sms("Usage: admin correct <first_name> <reps> [MMDD]")
        return
    first_name = parts[2].lower()
    try:
        reps = int(parts[3])
    except ValueError:
        send_admin_sms(f"Invalid reps: {parts[3]}")
        return

    tz = pytz.timezone(TIMEZONE)
    target_date = datetime.now(tz).date()
    if len(parts) >= 5:
        d = parts[4]
        if len(d) != 4 or not d.isdigit():
            send_admin_sms(f"Invalid date '{d}' (expected MMDD)")
            return
        try:
            target_date = date(target_date.year, int(d[:2]), int(d[2:]))
        except ValueError:
            send_admin_sms(f"Invalid date '{d}'")
            return

    people = load_people()
    match_phone = None
    match_name = None
    for phone, p in people.items():
        if p.get("name", "").split()[0].lower() == first_name:
            match_phone = phone
            match_name = p.get("name")
            break
    if not match_phone:
        send_admin_sms(f"No person found with first name '{first_name}'")
        return

    target_date_str = target_date.strftime("%Y-%m-%d")
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM logs WHERE phone=? AND date=?", (match_phone, target_date_str)
    ).fetchone()
    now_iso = datetime.now(pytz.timezone(TIMEZONE)).isoformat()
    if existing:
        conn.execute(
            "UPDATE logs SET reps=?, logged_at=? WHERE id=?",
            (reps, now_iso, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO logs (phone, reps, logged_at, date) VALUES (?, ?, ?, ?)",
            (match_phone, reps, now_iso, target_date_str),
        )
    conn.commit()
    conn.close()
    send_admin_sms(f"Updated {match_name} to {reps} reps for {target_date_str}")


@app.route("/sms", methods=["POST"])
def sms_reply():
    from_number = request.form.get("From", "")
    body = request.form.get("Body", "")
    people = load_people()

    if ADMIN_NUMBER and from_number == ADMIN_NUMBER and body.strip().lower().startswith("admin correct"):
        handle_admin_correct(body)
        return "", 204

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

def people_list(people):
    """Convert people dict to ordered list of {name, phone, photo} preserving insertion order."""
    return [{"name": p.get("name", ""), "phone": phone, "photo": p.get("photo", "")}
            for phone, p in people.items()]


def run_daily_recap(is_test=False):
    os.makedirs("recap_images", exist_ok=True)
    people = load_people()
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)

    if is_test:
        target_date = now.date()
    else:
        target_date = (now - timedelta(days=1)).date()
    target_date_str = get_date_str(target_date)

    entries = get_entries_for_date(target_date_str)

    if not entries and not is_test:
        return

    day_num = (target_date - CHALLENGE_START).days + 1

    plist = people_list(people)
    daily_logs = {}
    for entry in entries:
        person = people.get(entry["phone"])
        if person:
            daily_logs[person["name"]] = entry["reps"]

    img = generate_daily_recap(plist, daily_logs, target_date, day_num)
    filename = f"daily_{target_date_str}{'_test' if is_test else ''}.png"
    path = os.path.join("recap_images", filename)
    img.save(path)
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

    weekly_by_phone = {}
    for phone in people:
        weekly_by_phone[phone] = {"reps": 0, "days": 0, "points": 0}

    for row in rows:
        phone = row["phone"]
        if phone not in weekly_by_phone:
            continue
        reps = row["reps"]
        weekly_by_phone[phone]["reps"] += reps
        weekly_by_phone[phone]["days"] += 1
        weekly_by_phone[phone]["points"] += calculate_points(reps)

    plist = people_list(people)
    weekly_logs = {}
    for phone, data in weekly_by_phone.items():
        name = people[phone].get("name", "")
        weekly_logs[name] = data

    week_num = ((week_end - CHALLENGE_START).days // 7) + 1

    img = generate_weekly_recap(plist, weekly_logs, week_num, week_start, week_end)
    filename = f"weekly_{week_end_str}{'_test' if is_test else ''}.png"
    path = os.path.join("recap_images", filename)
    img.save(path)
    send_image_to_group(path)

scheduler = BackgroundScheduler(timezone=TIMEZONE)
scheduler.add_job(run_daily_recap, "cron", hour=9, minute=0)
scheduler.add_job(run_weekly_recap, "cron", day_of_week="mon", hour=9, minute=0)
scheduler.start()

os.makedirs("/data", exist_ok=True)
init_db()

if __name__ == "__main__":
    app.run(debug=False, port=5000)
