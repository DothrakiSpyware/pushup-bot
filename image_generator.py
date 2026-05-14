"""Recap image generation for the pushup challenge bot.

Public API:
    generate_daily_recap(people, daily_logs, target_date, day_number) -> PIL.Image
    generate_weekly_recap(people, weekly_logs, week_number, week_start, week_end) -> PIL.Image
    calculate_points(reps) -> int
"""

from PIL import Image, ImageDraw, ImageFont
from datetime import date as date_cls

CANVAS_W = 900
CANVAS_H = 1400

HEADER_H = 180
FOOTER_H = 60
ROW_H = 110

BG = (14, 16, 20)
BG_ROW = (22, 26, 33)
BG_ROW_ALT = (18, 21, 27)

HDR_DAILY_BG = (15, 52, 30)
HDR_DAILY_ACCENT = (34, 197, 94)
HDR_WEEKLY_BG = (10, 30, 65)
HDR_WEEKLY_ACCENT = (59, 130, 246)

GOLD = (255, 196, 0)
SILVER = (192, 192, 192)
BRONZE = (176, 112, 56)
RANK_DIM = (80, 85, 95)

TEXT_PRIMARY = (240, 242, 248)
TEXT_SECONDARY = (140, 148, 165)
TEXT_SKIP = (60, 65, 75)
WHITE = (255, 255, 255)
DARK_TEXT = (10, 12, 16)
DIVIDER = (32, 36, 45)

# Fixed per-person palette, cycled by the person's index in people.txt.
# Order: green, blue, orange, purple, red, teal, yellow, pink, indigo, lime
AVATAR_COLORS = [
    (34, 197, 94),
    (59, 130, 246),
    (249, 115, 22),
    (168, 85, 247),
    (239, 68, 68),
    (20, 184, 166),
    (234, 179, 8),
    (236, 72, 153),
    (99, 102, 241),
    (132, 204, 22),
]
SKIP_AVATAR = (40, 44, 52)

FONT_PATHS = {
    True: [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ],
    False: [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ],
}

_FONT_CACHE = {}


def load_font(size, bold=False):
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    for path in FONT_PATHS[bold] + FONT_PATHS[not bold]:
        try:
            f = ImageFont.truetype(path, size)
            _FONT_CACHE[key] = f
            return f
        except (OSError, IOError):
            continue
    f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


def calculate_points(reps):
    """Single source of truth for scoring.

    1-100 reps   -> 1 point per rep
    101-150 reps -> 0.5 points per rep
    151+ reps    -> 0.25 points per rep
    Hard cap of 150 points. Result is floored.
    """
    if reps is None or reps <= 0:
        return 0
    points = 0.0
    points += min(reps, 100) * 1.0
    if reps > 100:
        points += (min(reps, 150) - 100) * 0.5
    if reps > 150:
        points += (reps - 150) * 0.25
    return min(150, int(points))


def _first_name(full_name):
    parts = full_name.strip().split()
    return parts[0] if parts else ""


def _initials(full_name):
    parts = full_name.strip().split()
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][0].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _full_date(d):
    return d.strftime("%A, %B ") + str(d.day)


def _short_date(d):
    return d.strftime("%B ") + str(d.day)


def _rounded_rect(draw, xy, radius, fill=None, outline=None, width=1):
    try:
        draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)
    except AttributeError:
        draw.rectangle(xy, fill=fill, outline=outline, width=width)


def _rank_color(rank):
    return [GOLD, SILVER, BRONZE][rank] if rank < 3 else RANK_DIM


def _draw_header(draw, mode, day_or_week_text, big_date_text, sub_text):
    is_daily = mode == "daily"
    bg = HDR_DAILY_BG if is_daily else HDR_WEEKLY_BG
    accent = HDR_DAILY_ACCENT if is_daily else HDR_WEEKLY_ACCENT
    label = "DAILY RECAP" if is_daily else "WEEKLY RECAP"

    draw.rectangle([0, 0, CANVAS_W, HEADER_H], fill=bg)
    draw.rectangle([0, HEADER_H - 4, CANVAS_W, HEADER_H], fill=accent)

    # Left: pill badge
    pill_font = load_font(20, bold=True)
    pad_x, pad_y = 16, 7
    tw = draw.textlength(label, font=pill_font)
    px1, py1 = 32, 24
    px2 = px1 + int(tw) + pad_x * 2
    py2 = py1 + 20 + pad_y * 2
    _rounded_rect(draw, [px1, py1, px2, py2], radius=(py2 - py1) // 2,
                  outline=accent, width=2)
    draw.text(((px1 + px2) // 2, (py1 + py2) // 2), label,
              font=pill_font, fill=accent, anchor="mm")

    # Left: big date
    draw.text((32, 70), big_date_text, font=load_font(46, bold=True),
              fill=WHITE, anchor="lt")

    # Left: secondary line
    draw.text((34, 128), sub_text, font=load_font(24, bold=False),
              fill=TEXT_SECONDARY, anchor="lt")

    # Right: large day/week number badge
    bw, bh = 160, 116
    bx2, by1 = CANVAS_W - 32, 32
    bx1, by2 = bx2 - bw, by1 + bh
    _rounded_rect(draw, [bx1, by1, bx2, by2], radius=14, outline=accent, width=3)
    top_label, number = day_or_week_text
    draw.text(((bx1 + bx2) // 2, by1 + 24), top_label,
              font=load_font(20, bold=True), fill=accent, anchor="mm")
    draw.text(((bx1 + bx2) // 2, by1 + 74), str(number),
              font=load_font(60, bold=True), fill=WHITE, anchor="mm")


def _draw_avatar(draw, cx, cy, full_name, color):
    r = 30  # 60px diameter
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    draw.text((cx, cy), _initials(full_name), font=load_font(26, bold=True),
              fill=WHITE, anchor="mm")


def _draw_player_row(draw, y, rank, person_index, full_name, reps, points,
                     sub_value, alt_bg):
    bg = BG_ROW_ALT if alt_bg else BG_ROW
    cy = y + ROW_H // 2
    draw.rectangle([0, y, CANVAS_W, y + ROW_H], fill=bg)

    # Left accent stripe for the top 3 only
    if rank < 3:
        draw.rectangle([0, y, 5, y + ROW_H], fill=_rank_color(rank))

    # Rank number
    draw.text((54, cy), str(rank + 1), font=load_font(44, bold=True),
              fill=_rank_color(rank), anchor="mm")

    # Avatar
    _draw_avatar(draw, 150, cy, full_name,
                 AVATAR_COLORS[person_index % len(AVATAR_COLORS)])

    # Name + reps
    draw.text((205, cy - 16), _first_name(full_name),
              font=load_font(36, bold=True), fill=WHITE, anchor="lm")
    draw.text((205, cy + 24), sub_value, font=load_font(24, bold=False),
              fill=TEXT_SECONDARY, anchor="lm")

    # Points
    draw.text((CANVAS_W - 40, cy - 14), str(points),
              font=load_font(44, bold=True), fill=WHITE, anchor="rm")
    draw.text((CANVAS_W - 40, cy + 26), "pts", font=load_font(20, bold=False),
              fill=TEXT_SECONDARY, anchor="rm")

    draw.rectangle([0, y + ROW_H - 1, CANVAS_W, y + ROW_H], fill=DIVIDER)


def _draw_skip_row(draw, y, person_index, full_name, alt_bg):
    bg = BG_ROW_ALT if alt_bg else BG_ROW
    cy = y + ROW_H // 2
    draw.rectangle([0, y, CANVAS_W, y + ROW_H], fill=bg)

    _draw_avatar(draw, 150, cy, full_name, SKIP_AVATAR)

    draw.text((205, cy), _first_name(full_name), font=load_font(36, bold=True),
              fill=TEXT_SKIP, anchor="lm")
    draw.text((CANVAS_W - 40, cy - 14), "—", font=load_font(44, bold=True),
              fill=TEXT_SKIP, anchor="rm")
    draw.text((CANVAS_W - 40, cy + 26), "pts", font=load_font(20, bold=False),
              fill=TEXT_SKIP, anchor="rm")

    draw.rectangle([0, y + ROW_H - 1, CANVAS_W, y + ROW_H], fill=DIVIDER)


def _draw_skip_label(draw, y):
    draw.text((34, y + 22), "DID NOT LOG", font=load_font(18, bold=True),
              fill=TEXT_SKIP, anchor="lm")
    draw.line([180, y + 22, CANVAS_W - 34, y + 22], fill=DIVIDER, width=2)


def _draw_footer(draw, accent, logged_count, total_count, total_reps, period_label):
    fy = CANVAS_H - FOOTER_H
    draw.rectangle([0, fy, CANVAS_W, CANVAS_H], fill=BG_ROW)
    draw.rectangle([0, fy, CANVAS_W, fy + 2], fill=accent)
    font = load_font(24, bold=True)
    draw.text((32, fy + FOOTER_H // 2),
              f"{logged_count} of {total_count} logged {period_label}",
              font=font, fill=TEXT_SECONDARY, anchor="lm")
    draw.text((CANVAS_W - 32, fy + FOOTER_H // 2), f"Total: {total_reps} reps",
              font=font, fill=TEXT_SECONDARY, anchor="rm")


def _split_active_skipped(people, reps_for):
    active, skipped = [], []
    for idx, person in enumerate(people):
        name = person.get("name", "")
        reps = reps_for(name)
        if reps and reps > 0:
            active.append((idx, person, reps))
        else:
            skipped.append((idx, person))
    return active, skipped


def generate_daily_recap(people, daily_logs, target_date, day_number):
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), BG)
    draw = ImageDraw.Draw(img)

    _draw_header(draw, "daily", ("DAY", day_number),
                 _full_date(target_date), f"Day {day_number} of Challenge")

    active, skipped = _split_active_skipped(people, lambda n: daily_logs.get(n, 0))
    ranked = [(idx, p, reps, calculate_points(reps)) for idx, p, reps in active]
    ranked.sort(key=lambda t: (-t[3], -t[2], t[1].get("name", "")))

    y = HEADER_H
    for rank, (idx, person, reps, points) in enumerate(ranked):
        _draw_player_row(draw, y, rank, idx, person.get("name", ""), reps,
                         points, f"{reps} reps", alt_bg=(rank % 2 == 1))
        y += ROW_H

    if skipped:
        _draw_skip_label(draw, y)
        y += 44
        for j, (idx, person) in enumerate(skipped):
            _draw_skip_row(draw, y, idx, person.get("name", ""), alt_bg=(j % 2 == 1))
            y += ROW_H

    total_reps = sum(reps for _, _, reps, _ in ranked)
    _draw_footer(draw, HDR_DAILY_ACCENT, len(ranked), len(people), total_reps, "today")
    return img


def generate_weekly_recap(people, weekly_logs, week_number, week_start, week_end):
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), BG)
    draw = ImageDraw.Draw(img)

    big_date = f"{_short_date(week_start)} – {_short_date(week_end)}"
    _draw_header(draw, "weekly", ("WEEK", week_number),
                 big_date, f"Week {week_number} of Challenge")

    def reps_for(name):
        entry = weekly_logs.get(name)
        return entry.get("reps", 0) if entry else 0

    active, skipped = _split_active_skipped(people, reps_for)
    ranked = []
    for idx, person, reps in active:
        days = weekly_logs.get(person.get("name", ""), {}).get("days", 0)
        ranked.append((idx, person, reps, days, calculate_points(reps)))
    ranked.sort(key=lambda t: (-t[4], -t[2], t[1].get("name", "")))

    y = HEADER_H
    for rank, (idx, person, reps, days, points) in enumerate(ranked):
        _draw_player_row(draw, y, rank, idx, person.get("name", ""), reps,
                         points, f"{reps} reps · {days}/7 days",
                         alt_bg=(rank % 2 == 1))
        y += ROW_H

    if skipped:
        _draw_skip_label(draw, y)
        y += 44
        for j, (idx, person) in enumerate(skipped):
            _draw_skip_row(draw, y, idx, person.get("name", ""), alt_bg=(j % 2 == 1))
            y += ROW_H

    total_reps = sum(reps for _, _, reps, _, _ in ranked)
    _draw_footer(draw, HDR_WEEKLY_ACCENT, len(ranked), len(people), total_reps,
                 "this week")
    return img


if __name__ == "__main__":
    sample_people = [
        {"name": "Alex Johnson"},
        {"name": "Brooke Smith"},
        {"name": "Charlie Diaz"},
        {"name": "Dana Reyes"},
        {"name": "Evan Patel"},
        {"name": "Fiona Lee"},
        {"name": "Gabe Romano"},
    ]

    daily_logs = {
        "Alex Johnson": 120,
        "Brooke Smith": 85,
        "Charlie Diaz": 60,
        "Dana Reyes": 200,
        "Evan Patel": 30,
    }
    generate_daily_recap(sample_people, daily_logs,
                         date_cls(2026, 5, 14), 22).save("/tmp/preview_daily.png")

    weekly_logs = {
        "Alex Johnson": {"reps": 540, "days": 6},
        "Brooke Smith": {"reps": 410, "days": 5},
        "Charlie Diaz": {"reps": 320, "days": 4},
        "Dana Reyes": {"reps": 700, "days": 7},
        "Evan Patel": {"reps": 150, "days": 3},
        "Fiona Lee": {"reps": 90, "days": 2},
    }
    generate_weekly_recap(sample_people, weekly_logs, 4,
                          date_cls(2026, 5, 4), date_cls(2026, 5, 10)).save(
        "/tmp/preview_weekly.png")

    print("Wrote /tmp/preview_daily.png and /tmp/preview_weekly.png")
