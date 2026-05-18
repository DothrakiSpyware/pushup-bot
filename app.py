import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta, date
from functools import wraps

import pytz
import cloudinary
import cloudinary.uploader
from flask import Flask, request, session, redirect, url_for, jsonify, render_template_string
from twilio.rest import Client
from apscheduler.schedulers.background import BackgroundScheduler

from image_generator import generate_daily_recap, generate_weekly_recap, calculate_points

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-insecure-change-me")

ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")
CLOUDINARY_URL = os.environ.get("CLOUDINARY_URL")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

EASTERN = pytz.timezone("America/New_York")
CHALLENGE_START = date(2026, 5, 18)
API_CHALLENGE_START = date(2026, 5, 12)

DB_PATH = "/data/pushups.db"
PEOPLE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "people.txt")

os.makedirs("/data", exist_ok=True)


# --------------------------------------------------------------------------
# People
# --------------------------------------------------------------------------
def normalize_phone(phone):
    return re.sub(r"[^\d+]", "", phone or "")


def load_people():
    """Parse people.txt into (members, moderators)."""
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


REQUIRED_COLUMNS = {"id", "phone", "name", "date", "reps", "timestamp"}


def init_db():
    conn = get_db()
    table_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='logs'"
    ).fetchone()
    if table_exists:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(logs)")}
        if not REQUIRED_COLUMNS.issubset(columns):
            print("logs table missing required columns; dropping and recreating")
            conn.execute("DROP TABLE logs")

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
    conn = get_db()
    conn.execute(
        """
        INSERT INTO logs (phone, name, date, reps, timestamp)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(phone, date) DO UPDATE SET
            reps = logs.reps + excluded.reps,
            name = excluded.name,
            timestamp = excluded.timestamp
        """,
        (phone, name, log_date.isoformat(), reps, now_eastern().isoformat()),
    )
    conn.commit()
    conn.close()


def set_log(phone, name, log_date, reps):
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
        entry = logs.setdefault(name, {"reps": 0, "days": 0, "min_daily_reps": None})
        entry["reps"] += row["reps"]
        entry["days"] += 1
        if entry["min_daily_reps"] is None or row["reps"] < entry["min_daily_reps"]:
            entry["min_daily_reps"] = row["reps"]
    return logs


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def now_eastern():
    return datetime.now(EASTERN)


REP_KEYWORDS = [
    "pushups", "push-ups", "pushup", "push-up", "push",
    "reps", "rep", "logging", "log", "knocked", "completed",
    "finished", "done", "did", "do",
]
TIME_WORDS = [
    "am", "pm", "o'clock", "tonight", "tomorrow",
    "yesterday", "morning", "night",
]
_REP_KEYWORD_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in REP_KEYWORDS) + r")\b", re.IGNORECASE
)
_TIME_WORD_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in TIME_WORDS) + r")\b", re.IGNORECASE
)


def parse_reps(body):
    text = body.strip()
    if ":" in text or _TIME_WORD_RE.search(text):
        return None
    numbers = re.findall(r"\d+", text)
    if len(numbers) != 1:
        return None
    reps = int(numbers[0])
    if not (1 <= reps <= 500):
        return None
    if re.fullmatch(r"\d+", text) or _REP_KEYWORD_RE.search(text):
        return reps
    return None


# --------------------------------------------------------------------------
# Report generation + delivery
# --------------------------------------------------------------------------
def send_mms_to_recipients(image_path, recipients):
    cloudinary.config(cloudinary_url=CLOUDINARY_URL)
    result = cloudinary.uploader.upload(image_path, resource_type="image", format="png")
    image_url = result["secure_url"]
    print(f"Uploaded recap image: {image_url}")

    client = Client(ACCOUNT_SID, AUTH_TOKEN)
    for r in recipients:
        try:
            msg = client.messages.create(
                to=r["phone"], from_=TWILIO_NUMBER, media_url=[image_url]
            )
            print(f"Sent recap to {r['phone']}: {msg.sid}")
        except Exception as e:
            print(f"Failed to send recap to {r['phone']}: {e}")


def send_daily_report(recipients=None):
    try:
        members, moderators = load_people()
        if recipients is None:
            recipients = moderators
        if not recipients:
            print("No recipients configured; skipping daily report")
            return
        target_date = now_eastern().date()
        day_number = (target_date - CHALLENGE_START).days + 1
        logs = daily_logs_for(members, target_date)
        img = generate_daily_recap(members, logs, target_date, day_number)
        path = "/tmp/recap_daily.png"
        img.save(path)
        send_mms_to_recipients(path, recipients)
    except Exception as e:
        print(f"send_daily_report failed: {e}")


def send_weekly_report(week_start=None, week_end=None, recipients=None, to_all_members=False):
    try:
        members, moderators = load_people()
        if recipients is None:
            recipients = members if to_all_members else moderators
        if not recipients:
            print("No recipients configured; skipping weekly report")
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
        send_mms_to_recipients(path, recipients)
    except Exception as e:
        print(f"send_weekly_report failed: {e}")


def scheduled_weekly_report():
    """Monday 9:00 AM ET: recap the previous complete Mon-Sun week to all members."""
    today = now_eastern().date()
    this_monday = today - timedelta(days=today.weekday())
    send_weekly_report(this_monday - timedelta(days=7), this_monday - timedelta(days=1),
                       to_all_members=True)


# --------------------------------------------------------------------------
# Admin correction (moderators only via SMS)
# --------------------------------------------------------------------------
def handle_admin_correct(body, members):
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

    set_log(target["phone"], target["name"], target_date, reps)
    print(f"Admin correction: {target['name']} -> {reps} reps on {target_date}")


# --------------------------------------------------------------------------
# SMS Webhook
# --------------------------------------------------------------------------
DISPLAY_DAILY_PHRASES = {"display daily report", "send daily report"}
DISPLAY_WEEKLY_PHRASES = {"display weekly report", "send weekly report"}


@app.route("/sms", methods=["POST"])
def sms():
    from_number = normalize_phone(request.form.get("From", ""))
    body = (request.form.get("Body", "") or "").strip()
    members, moderators = load_people()

    member_by_phone = {m["phone"]: m for m in members}
    moderator_phones = {m["phone"] for m in moderators}
    is_moderator = from_number in moderator_phones
    member = member_by_phone.get(from_number)
    text = body.lower()

    # Any recognized member can request a report; result sent only to them.
    if member:
        if text in DISPLAY_DAILY_PHRASES:
            threading.Thread(
                target=send_daily_report, kwargs={"recipients": [member]}, daemon=True
            ).start()
            return ("", 200)
        if text in DISPLAY_WEEKLY_PHRASES:
            threading.Thread(
                target=send_weekly_report, kwargs={"recipients": [member]}, daemon=True
            ).start()
            return ("", 200)

    if is_moderator and text.startswith("admin correct"):
        handle_admin_correct(body, members)
        return ("", 200)

    if member:
        reps = parse_reps(body)
        if reps is not None:
            upsert_log(member["phone"], member["name"], now_eastern().date(), reps)

    return ("", 200)


# --------------------------------------------------------------------------
# Public JSON API (CORS open for GitHub Pages site)
# --------------------------------------------------------------------------
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


def _all_logs_since(start_date):
    conn = get_db()
    rows = conn.execute(
        "SELECT phone, date, reps FROM logs WHERE date >= ?",
        (start_date.isoformat(),),
    ).fetchall()
    conn.close()
    return rows


@app.route("/api/daily")
def api_daily():
    members, _ = load_people()
    today = now_eastern().date()
    logs = daily_logs_for(members, today)
    entries = []
    for m in members:
        reps = logs.get(m["name"], 0)
        entries.append({
            "name": m["name"],
            "reps": reps,
            "points": calculate_points(reps),
        })
    entries.sort(key=lambda e: e["points"], reverse=True)
    for i, e in enumerate(entries, 1):
        e["rank"] = i
    day_number = (today - API_CHALLENGE_START).days + 1
    return _cors(jsonify({
        "data": entries,
        "date": today.isoformat(),
        "day_number": day_number,
        "last_updated": now_eastern().isoformat(),
    }))


@app.route("/api/monthly")
def api_monthly():
    members, _ = load_people()
    by_phone = {m["phone"]: m["name"] for m in members}
    today = now_eastern().date()
    month_start = today.replace(day=1)
    rows = _all_logs_since(month_start)

    totals = {m["name"]: {"name": m["name"], "total_reps": 0, "total_points": 0, "days_logged": 0}
              for m in members}
    for row in rows:
        name = by_phone.get(normalize_phone(row["phone"]))
        if not name:
            continue
        t = totals[name]
        t["total_reps"] += row["reps"]
        t["total_points"] += calculate_points(row["reps"])
        t["days_logged"] += 1

    data = sorted(totals.values(), key=lambda e: e["total_points"], reverse=True)
    return _cors(jsonify({
        "data": data,
        "last_updated": now_eastern().isoformat(),
    }))


@app.route("/api/alltime")
def api_alltime():
    members, _ = load_people()
    by_phone = {m["phone"]: m["name"] for m in members}
    rows = _all_logs_since(API_CHALLENGE_START)

    totals = {m["name"]: {"name": m["name"], "total_reps": 0, "total_points": 0, "days_logged": 0}
              for m in members}
    for row in rows:
        name = by_phone.get(normalize_phone(row["phone"]))
        if not name:
            continue
        t = totals[name]
        t["total_reps"] += row["reps"]
        t["total_points"] += calculate_points(row["reps"])
        t["days_logged"] += 1

    data = sorted(totals.values(), key=lambda e: e["total_points"], reverse=True)
    return _cors(jsonify({
        "data": data,
        "last_updated": now_eastern().isoformat(),
    }))


# --------------------------------------------------------------------------
# Admin panel
# --------------------------------------------------------------------------
def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapped


LOGIN_TEMPLATE = """
<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin Login</title>
<style>
  body{background:#0a0a0f;color:#fff;font-family:-apple-system,system-ui,sans-serif;
       display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;}
  .card{background:#1a1a2e;padding:32px;border-radius:12px;width:90%;max-width:340px;
        box-shadow:0 8px 32px rgba(0,0,0,.4);}
  h1{margin:0 0 16px;color:#00ff88;font-size:22px;}
  input{width:100%;padding:12px;margin:8px 0 16px;background:#0a0a0f;color:#fff;
        border:1px solid #333;border-radius:6px;box-sizing:border-box;font-size:16px;}
  button{width:100%;padding:12px;background:#00ff88;color:#0a0a0f;border:0;
         border-radius:6px;font-weight:700;font-size:16px;cursor:pointer;}
  .err{color:#ff5577;margin-bottom:8px;font-size:14px;}
</style></head><body>
<form class="card" method="post">
  <h1>Admin</h1>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  <input type="password" name="password" placeholder="Password" autofocus>
  <button type="submit">Log in</button>
</form></body></html>
"""

ADMIN_TEMPLATE = """
<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pushup Admin</title>
<style>
  *{box-sizing:border-box;}
  body{background:#0a0a0f;color:#fff;font-family:-apple-system,system-ui,sans-serif;
       margin:0;padding:16px;}
  h1{color:#00ff88;margin:0;font-size:22px;}
  h2{color:#00ff88;margin:0 0 12px;font-size:18px;}
  .topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;}
  .card{background:#1a1a2e;padding:16px;border-radius:12px;margin-bottom:20px;
        box-shadow:0 4px 16px rgba(0,0,0,.3);overflow-x:auto;}
  table{width:100%;border-collapse:collapse;font-size:14px;min-width:560px;}
  th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #2a2a3e;}
  th{color:#888;font-weight:600;text-transform:uppercase;font-size:11px;letter-spacing:.5px;}
  tr:hover td{background:#222238;}
  button,input[type=submit]{background:#00ff88;color:#0a0a0f;border:0;padding:6px 12px;
                            border-radius:6px;font-weight:700;cursor:pointer;font-size:13px;}
  button.danger{background:#ff5577;color:#fff;}
  button.secondary{background:#333;color:#fff;}
  input,select{background:#0a0a0f;color:#fff;border:1px solid #333;
               padding:8px;border-radius:6px;font-size:14px;}
  .row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;}
  .row > *{flex:0 0 auto;}
  form.inline{display:inline;}
  .yes{color:#00ff88;}
  .no{color:#666;}
  .btnrow{display:flex;gap:6px;}
  .logout{background:#333;color:#fff;text-decoration:none;padding:8px 14px;border-radius:6px;
          font-size:13px;}
</style></head><body>
<div class="topbar">
  <h1>Pushup Admin</h1>
  <a class="logout" href="{{ url_for('admin_logout') }}">Log out</a>
</div>

<div class="card">
  <h2>Logs ({{ logs|length }})</h2>
  <table>
    <thead><tr>
      <th>ID</th><th>Name</th><th>Phone</th><th>Date</th>
      <th>Reps</th><th>Points</th><th>Timestamp</th><th></th>
    </tr></thead>
    <tbody>
    {% for row in logs %}
      <tr>
        <td>{{ row.id }}</td>
        <td>{{ row.name }}</td>
        <td>{{ row.phone }}</td>
        <td>{{ row.date }}</td>
        <td>
          <form class="inline" method="post" action="{{ url_for('admin_edit') }}">
            <input type="hidden" name="id" value="{{ row.id }}">
            <input type="number" name="reps" value="{{ row.reps }}" min="0" max="2000"
                   style="width:80px">
            <button type="submit">Save</button>
          </form>
        </td>
        <td>{{ row.points }}</td>
        <td>{{ row.timestamp }}</td>
        <td>
          <form class="inline" method="post" action="{{ url_for('admin_delete') }}"
                onsubmit="return confirm('Delete log {{ row.id }}?');">
            <input type="hidden" name="id" value="{{ row.id }}">
            <button class="danger" type="submit">Delete</button>
          </form>
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
</div>

<div class="card">
  <h2>Members (from people.txt)</h2>
  <table>
    <thead><tr><th>Name</th><th>Phone</th><th>Member</th><th>Moderator</th></tr></thead>
    <tbody>
    {% for p in people_list %}
      <tr>
        <td>{{ p.name }}</td>
        <td>{{ p.phone }}</td>
        <td>{% if p.is_member %}<span class="yes">YES</span>{% else %}<span class="no">no</span>{% endif %}</td>
        <td>{% if p.is_mod %}<span class="yes">YES</span>{% else %}<span class="no">no</span>{% endif %}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
</div>

<div class="card">
  <h2>Manual actions</h2>
  <form method="post" action="{{ url_for('admin_add') }}" class="row" style="margin-bottom:16px">
    <select name="phone" required>
      {% for m in members %}
        <option value="{{ m.phone }}">{{ m.name }}</option>
      {% endfor %}
    </select>
    <input type="date" name="date" value="{{ today }}" required>
    <input type="number" name="reps" placeholder="reps" min="1" max="2000" required style="width:100px">
    <button type="submit">Add log</button>
  </form>
  <form method="post" action="{{ url_for('admin_trigger_weekly') }}" class="inline">
    <button type="submit"
            onclick="return confirm('Send weekly report to ALL members now?');">
      Send weekly report to all members
    </button>
  </form>
  <form method="post" action="{{ url_for('admin_trigger_daily') }}" class="inline">
    <button class="secondary" type="submit"
            onclick="return confirm('Send daily report to ALL members now?');">
      Send daily report to all members
    </button>
  </form>
</div>

</body></html>
"""


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if ADMIN_PASSWORD and request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin"))
        error = "Incorrect password."
    return render_template_string(LOGIN_TEMPLATE, error=error)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
@admin_required
def admin():
    members, moderators = load_people()
    mod_phones = {m["phone"] for m in moderators}
    mem_phones = {m["phone"] for m in members}
    seen = set()
    people_list = []
    for p in members + moderators:
        key = (p["name"], p["phone"])
        if key in seen:
            continue
        seen.add(key)
        people_list.append({
            "name": p["name"],
            "phone": p["phone"],
            "is_member": p["phone"] in mem_phones,
            "is_mod": p["phone"] in mod_phones,
        })

    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, phone, date, reps, timestamp FROM logs "
        "ORDER BY date DESC, reps DESC"
    ).fetchall()
    conn.close()
    logs = []
    for r in rows:
        d = dict(r)
        d["points"] = calculate_points(r["reps"])
        logs.append(d)
    # Final sort: date DESC, points DESC (overrides reps tiebreak)
    logs.sort(key=lambda x: (x["date"], x["points"]), reverse=True)

    return render_template_string(
        ADMIN_TEMPLATE,
        logs=logs,
        people_list=people_list,
        members=members,
        today=now_eastern().date().isoformat(),
    )


@app.route("/admin/edit", methods=["POST"])
@admin_required
def admin_edit():
    try:
        log_id = int(request.form["id"])
        reps = int(request.form["reps"])
    except (KeyError, ValueError):
        return redirect(url_for("admin"))
    conn = get_db()
    conn.execute("UPDATE logs SET reps = ? WHERE id = ?", (reps, log_id))
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))


@app.route("/admin/delete", methods=["POST"])
@admin_required
def admin_delete():
    try:
        log_id = int(request.form["id"])
    except (KeyError, ValueError):
        return redirect(url_for("admin"))
    conn = get_db()
    conn.execute("DELETE FROM logs WHERE id = ?", (log_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))


@app.route("/admin/add", methods=["POST"])
@admin_required
def admin_add():
    phone = normalize_phone(request.form.get("phone", ""))
    date_str = request.form.get("date", "")
    try:
        reps = int(request.form.get("reps", "0"))
        log_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return redirect(url_for("admin"))
    members, _ = load_people()
    target = next((m for m in members if m["phone"] == phone), None)
    if not target or reps <= 0:
        return redirect(url_for("admin"))
    set_log(target["phone"], target["name"], log_date, reps)
    return redirect(url_for("admin"))


@app.route("/admin/trigger-weekly", methods=["POST"])
@admin_required
def admin_trigger_weekly():
    threading.Thread(
        target=send_weekly_report, kwargs={"to_all_members": True}, daemon=True
    ).start()
    return redirect(url_for("admin"))


@app.route("/admin/trigger-daily", methods=["POST"])
@admin_required
def admin_trigger_daily():
    def _all_members():
        members, _ = load_people()
        send_daily_report(recipients=members)
    threading.Thread(target=_all_members, daemon=True).start()
    return redirect(url_for("admin"))


# --------------------------------------------------------------------------
# Startup
# --------------------------------------------------------------------------
init_db()

scheduler = BackgroundScheduler(timezone=EASTERN)
scheduler.add_job(scheduled_weekly_report, "cron", day_of_week="mon", hour=9, minute=0)
scheduler.start()

if __name__ == "__main__":
    app.run(debug=False, port=5000)
