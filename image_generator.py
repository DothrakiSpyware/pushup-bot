from PIL import Image, ImageDraw, ImageFont
from datetime import date as date_cls

CANVAS_W = 900
CANVAS_H = 1400

BG = (14, 16, 20)
BG_ROW = (22, 26, 33)
BG_ROW_ALT = (18, 21, 27)
BG_SKIP = (16, 18, 22)

HDR_DAILY = (15, 52, 30)
HDR_WEEKLY = (10, 30, 65)
HDR_DAILY_ACCENT = (34, 197, 94)
HDR_WEEKLY_ACCENT = (59, 130, 246)

GOLD = (255, 196, 0)
SILVER = (192, 192, 192)
BRONZE = (176, 112, 56)
RANK_DIM = (80, 85, 95)

TEXT_PRIMARY = (240, 242, 248)
TEXT_SECONDARY = (140, 148, 165)
TEXT_SKIP = (60, 65, 75)
DIVIDER = (30, 35, 45)

DARK_TEXT = (10, 10, 14)

AVATAR_COLORS = [
    {"fg": (34, 197, 94),   "bg": (10, 50, 20)},
    {"fg": (59, 130, 246),  "bg": (10, 30, 70)},
    {"fg": (251, 146, 60),  "bg": (60, 25, 5)},
    {"fg": (167, 139, 250), "bg": (40, 20, 70)},
    {"fg": (236, 72, 153),  "bg": (60, 15, 40)},
    {"fg": (20, 184, 166),  "bg": (5, 45, 42)},
    {"fg": (245, 158, 11),  "bg": (55, 35, 5)},
    {"fg": (248, 113, 113), "bg": (65, 15, 15)},
    {"fg": (99, 102, 241),  "bg": (25, 20, 65)},
    {"fg": (16, 185, 129),  "bg": (5, 45, 28)},
]

SKIP_AVATAR = {"fg": TEXT_SKIP, "bg": (28, 30, 36)}

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
    for path in FONT_PATHS[bold]:
        try:
            f = ImageFont.truetype(path, size)
            _FONT_CACHE[key] = f
            return f
        except (OSError, IOError):
            continue
    # Fallback paths from the opposite weight, then default
    for path in FONT_PATHS[not bold]:
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
    if reps <= 0:
        return 0
    if reps <= 100:
        return int(reps)
    if reps <= 150:
        return int(100 + (reps - 100) * 0.5)
    if reps <= 200:
        return int(100 + 25 + (reps - 150) * 0.25)
    return 150


def _first_name(full_name):
    return full_name.strip().split()[0] if full_name.strip() else ""


def _initials(full_name):
    parts = full_name.strip().split()
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][0].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _rounded_rect(draw, xy, radius, fill=None, outline=None, width=1):
    try:
        draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)
    except AttributeError:
        x1, y1, x2, y2 = xy
        if fill is not None:
            draw.rectangle([x1 + radius, y1, x2 - radius, y2], fill=fill)
            draw.rectangle([x1, y1 + radius, x2, y2 - radius], fill=fill)
            draw.pieslice([x1, y1, x1 + 2*radius, y1 + 2*radius], 180, 270, fill=fill)
            draw.pieslice([x2 - 2*radius, y1, x2, y1 + 2*radius], 270, 360, fill=fill)
            draw.pieslice([x1, y2 - 2*radius, x1 + 2*radius, y2], 90, 180, fill=fill)
            draw.pieslice([x2 - 2*radius, y2 - 2*radius, x2, y2], 0, 90, fill=fill)
        if outline is not None:
            draw.rectangle([x1, y1, x2, y2], outline=outline, width=width)


def _draw_avatar(img, draw, cx, cy, radius, initials, colors):
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=colors["bg"])
    font = load_font(28, bold=True)
    draw.text((cx, cy), initials, font=font, fill=colors["fg"], anchor="mm")


def _draw_header(draw, img, mode, primary_label, day_or_week_text, big_date_text, sub_date_text):
    is_daily = mode == "daily"
    bg_color = HDR_DAILY if is_daily else HDR_WEEKLY
    accent = HDR_DAILY_ACCENT if is_daily else HDR_WEEKLY_ACCENT

    draw.rectangle([0, 0, CANVAS_W, 200], fill=bg_color)
    draw.rectangle([0, 0, CANVAS_W, 5], fill=accent)

    # Pill badge left
    pill_font = load_font(22, bold=True)
    pad_x, pad_y = 18, 8
    tw = draw.textlength(primary_label, font=pill_font)
    pill_x1 = 30
    pill_y1 = 28
    pill_x2 = pill_x1 + int(tw) + pad_x * 2
    pill_y2 = pill_y1 + 22 + pad_y * 2
    _rounded_rect(draw, [pill_x1, pill_y1, pill_x2, pill_y2], radius=(pill_y2 - pill_y1) // 2, fill=accent)
    draw.text(((pill_x1 + pill_x2) // 2, (pill_y1 + pill_y2) // 2), primary_label,
              font=pill_font, fill=DARK_TEXT, anchor="mm")

    # Right badge (outline, accent text)
    badge_font = load_font(24, bold=True)
    bw = int(draw.textlength(day_or_week_text, font=badge_font)) + 32
    bh = 48
    bx2 = CANVAS_W - 30
    bx1 = bx2 - bw
    by1 = 28
    by2 = by1 + bh
    _rounded_rect(draw, [bx1, by1, bx2, by2], radius=10, outline=accent, width=3)
    draw.text(((bx1 + bx2) // 2, (by1 + by2) // 2), day_or_week_text,
              font=badge_font, fill=accent, anchor="mm")

    # Big date text
    big_font = load_font(58, bold=True)
    draw.text((30, 100), big_date_text, font=big_font, fill=TEXT_PRIMARY, anchor="lt")

    # Secondary line
    sub_font = load_font(26, bold=False)
    draw.text((30, 165), sub_date_text, font=sub_font, fill=TEXT_PRIMARY, anchor="lt")

    # Accent line at bottom of header
    draw.rectangle([0, 198, CANVAS_W, 200], fill=accent)


def _draw_column_headers(draw, y, weekly=False):
    font = load_font(18, bold=True)
    draw.text((40, y), "#", font=font, fill=TEXT_SECONDARY, anchor="lm")
    draw.text((150, y), "PLAYER", font=font, fill=TEXT_SECONDARY, anchor="lm")
    if weekly:
        draw.text((CANVAS_W - 200, y), "DAYS", font=font, fill=TEXT_SECONDARY, anchor="mm")
    draw.text((CANVAS_W - 40, y), "PTS", font=font, fill=TEXT_SECONDARY, anchor="rm")
    draw.rectangle([20, y + 18, CANVAS_W - 20, y + 19], fill=DIVIDER)


def _rank_color(rank):
    if rank == 0:
        return GOLD
    if rank == 1:
        return SILVER
    if rank == 2:
        return BRONZE
    return RANK_DIM


def _draw_player_row(img, draw, y, row_h, rank, person_index, full_name, primary_value,
                     sub_value, alt_bg, sub_extra=None, weekly_days_text=None):
    bg = BG_ROW_ALT if alt_bg else BG_ROW
    draw.rectangle([0, y, CANVAS_W, y + row_h], fill=bg)

    if rank < 3:
        draw.rectangle([0, y, 4, y + row_h], fill=_rank_color(rank))

    rank_font = load_font(40, bold=True)
    draw.text((50, y + row_h // 2), str(rank + 1), font=rank_font,
              fill=_rank_color(rank), anchor="mm")

    colors = AVATAR_COLORS[person_index % len(AVATAR_COLORS)]
    _draw_avatar(img, draw, 150, y + row_h // 2, 34, _initials(full_name), colors)

    first_name_font = load_font(36, bold=True)
    if weekly_days_text:
        draw.text((200, y + row_h // 2 - 14), _first_name(full_name),
                  font=first_name_font, fill=TEXT_PRIMARY, anchor="lm")
        days_font = load_font(22, bold=False)
        draw.text((200, y + row_h // 2 + 22), weekly_days_text,
                  font=days_font, fill=TEXT_SECONDARY, anchor="lm")
    else:
        draw.text((200, y + row_h // 2), _first_name(full_name),
                  font=first_name_font, fill=TEXT_PRIMARY, anchor="lm")

    primary_font = load_font(42, bold=True)
    sub_font = load_font(26, bold=False)
    draw.text((CANVAS_W - 40, y + row_h // 2 - 14), str(primary_value),
              font=primary_font, fill=TEXT_PRIMARY, anchor="rm")
    draw.text((CANVAS_W - 40, y + row_h // 2 + 22), sub_value,
              font=sub_font, fill=TEXT_SECONDARY, anchor="rm")

    draw.rectangle([20, y + row_h - 1, CANVAS_W - 20, y + row_h], fill=DIVIDER)


def _draw_skip_row(img, draw, y, row_h, person_index, full_name, alt_bg):
    draw.rectangle([0, y, CANVAS_W, y + row_h], fill=BG_SKIP)

    colors = SKIP_AVATAR
    _draw_avatar(img, draw, 150, y + row_h // 2, 34, _initials(full_name), colors)

    name_font = load_font(36, bold=True)
    draw.text((200, y + row_h // 2), _first_name(full_name),
              font=name_font, fill=TEXT_SKIP, anchor="lm")

    dash_font = load_font(42, bold=True)
    draw.text((CANVAS_W - 40, y + row_h // 2 - 14), "—",
              font=dash_font, fill=TEXT_SKIP, anchor="rm")
    sub_font = load_font(26, bold=False)
    draw.text((CANVAS_W - 40, y + row_h // 2 + 22), "—",
              font=sub_font, fill=TEXT_SKIP, anchor="rm")

    draw.rectangle([20, y + row_h - 1, CANVAS_W - 20, y + row_h], fill=DIVIDER)


def _draw_skip_label(draw, y, text, accent):
    font = load_font(20, bold=True)
    draw.text((30, y + 16), text, font=font, fill=TEXT_SECONDARY, anchor="lm")
    draw.rectangle([20, y + 34, CANVAS_W - 20, y + 35], fill=DIVIDER)


def _draw_footer(draw, accent, active_count, total_reps):
    fy = CANVAS_H - 100
    draw.rectangle([0, fy, CANVAS_W, CANVAS_H], fill=BG_ROW)
    draw.rectangle([0, fy, CANVAS_W, fy + 2], fill=accent)

    font = load_font(26, bold=True)
    draw.text((30, fy + 50), f"{active_count} ACTIVE", font=font,
              fill=TEXT_SECONDARY, anchor="lm")
    draw.text((CANVAS_W - 30, fy + 50), f"{total_reps} TOTAL REPS",
              font=font, fill=TEXT_SECONDARY, anchor="rm")


def generate_daily_recap(people, daily_logs, target_date, day_number):
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), BG)
    draw = ImageDraw.Draw(img)

    big_date = target_date.strftime("%b %d").upper()
    weekday = target_date.strftime("%A, %B %d %Y")
    _draw_header(draw, img, "daily", "DAILY RECAP", f"DAY {day_number}", big_date, weekday)

    # Build active + skipped lists by index in people
    indexed = list(enumerate(people))
    active = []
    skipped = []
    for idx, p in indexed:
        name = p.get("name", "")
        reps = daily_logs.get(name, 0)
        if reps and reps > 0:
            active.append((idx, p, reps, calculate_points(reps)))
        else:
            skipped.append((idx, p))

    active.sort(key=lambda t: (-t[3], -t[2], t[1].get("name", "")))

    y = 210
    _draw_column_headers(draw, y + 18)
    y += 40

    row_h = 100
    for rank, (idx, p, reps, pts) in enumerate(active):
        _draw_player_row(img, draw, y, row_h, rank, idx, p.get("name", ""),
                         reps, f"{pts} pts", alt_bg=(rank % 2 == 1))
        y += row_h

    if skipped:
        _draw_skip_label(draw, y, "DID NOT LOG", HDR_DAILY_ACCENT)
        y += 36
        for j, (idx, p) in enumerate(skipped):
            _draw_skip_row(img, draw, y, row_h, idx, p.get("name", ""), alt_bg=(j % 2 == 1))
            y += row_h

    total_reps = sum(t[2] for t in active)
    _draw_footer(draw, HDR_DAILY_ACCENT, len(active), total_reps)

    return img


def generate_weekly_recap(people, weekly_logs, week_number, week_start, week_end):
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), BG)
    draw = ImageDraw.Draw(img)

    big_date = f"{week_start.strftime('%b %d').upper()} – {week_end.strftime('%b %d').upper()}"
    sub_line = f"Week of {week_start.strftime('%B %d')} – {week_end.strftime('%B %d, %Y')}"
    _draw_header(draw, img, "weekly", "WEEKLY RECAP", f"WK {week_number}", big_date, sub_line)

    indexed = list(enumerate(people))
    active = []
    skipped = []
    for idx, p in indexed:
        name = p.get("name", "")
        entry = weekly_logs.get(name)
        if entry and entry.get("reps", 0) > 0:
            reps = entry["reps"]
            days = entry.get("days", 0)
            pts = entry.get("points")
            if pts is None:
                pts = calculate_points(reps)
            active.append((idx, p, reps, days, pts))
        else:
            skipped.append((idx, p))

    active.sort(key=lambda t: (-t[4], -t[2], t[1].get("name", "")))

    y = 210
    _draw_column_headers(draw, y + 18, weekly=True)
    y += 40

    row_h = 100
    for rank, (idx, p, reps, days, pts) in enumerate(active):
        _draw_player_row(img, draw, y, row_h, rank, idx, p.get("name", ""),
                         reps, f"{pts} pts", alt_bg=(rank % 2 == 1),
                         weekly_days_text=f"{days}/7 days")
        y += row_h

    if skipped:
        _draw_skip_label(draw, y, "NO ACTIVITY", HDR_WEEKLY_ACCENT)
        y += 36
        for j, (idx, p) in enumerate(skipped):
            _draw_skip_row(img, draw, y, row_h, idx, p.get("name", ""), alt_bg=(j % 2 == 1))
            y += row_h

    total_reps = sum(t[2] for t in active)
    _draw_footer(draw, HDR_WEEKLY_ACCENT, len(active), total_reps)

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
    img = generate_daily_recap(sample_people, daily_logs, date_cls(2025, 1, 15), 22)
    img.save("/tmp/preview_daily.png")

    weekly_logs = {
        "Alex Johnson": {"reps": 540, "days": 6},
        "Brooke Smith": {"reps": 410, "days": 5},
        "Charlie Diaz": {"reps": 320, "days": 4},
        "Dana Reyes":   {"reps": 700, "days": 7},
        "Evan Patel":   {"reps": 150, "days": 3},
        "Fiona Lee":    {"reps": 90,  "days": 2},
    }
    img2 = generate_weekly_recap(sample_people, weekly_logs, 4,
                                 date_cls(2025, 1, 13), date_cls(2025, 1, 19))
    img2.save("/tmp/preview_weekly.png")
    print("Wrote /tmp/preview_daily.png and /tmp/preview_weekly.png")
