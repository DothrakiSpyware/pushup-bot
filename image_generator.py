from PIL import Image, ImageDraw, ImageFont
import os
import requests
from io import BytesIO
from datetime import datetime

CARD_W = 900
DAILY_COLOR = (15, 80, 40)
WEEKLY_COLOR = (15, 30, 90)
BG_COLOR = (12, 22, 32)
ROW_BG = (18, 34, 48)
TEXT_PRIMARY = (232, 240, 245)
TEXT_MUTED = (80, 110, 130)
GOLD = (245, 197, 66)
SILVER = (176, 184, 193)
BRONZE = (205, 127, 50)
GREEN_ACCENT = (109, 220, 154)
BLUE_ACCENT = (109, 154, 220)

RANK_COLORS = [GOLD, SILVER, BRONZE]

def load_font(size, bold=False):
    try:
        if bold:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()

def score_from_reps(reps):
    if reps <= 0:
        return 0
    elif reps <= 100:
        return reps
    elif reps <= 200:
        return 100 + int((reps - 100) * 0.5)
    else:
        return 150

def draw_rounded_rect(draw, xy, radius, fill):
    x1, y1, x2, y2 = xy
    draw.rectangle([x1 + radius, y1, x2 - radius, y2], fill=fill)
    draw.rectangle([x1, y1 + radius, x2, y2 - radius], fill=fill)
    draw.ellipse([x1, y1, x1 + radius*2, y1 + radius*2], fill=fill)
    draw.ellipse([x2 - radius*2, y1, x2, y1 + radius*2], fill=fill)
    draw.ellipse([x1, y2 - radius*2, x1 + radius*2, y2], fill=fill)
    draw.ellipse([x2 - radius*2, y2 - radius*2, x2, y2], fill=fill)

def draw_avatar(img, center_x, center_y, radius, photo_path, initials, color):
    mask = Image.new("L", (radius*2, radius*2), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse([0, 0, radius*2, radius*2], fill=255)
    loaded = False
    if photo_path and os.path.exists(photo_path):
        try:
            av = Image.open(photo_path).convert("RGBA").resize((radius*2, radius*2))
            img.paste(av, (center_x - radius, center_y - radius), mask)
            loaded = True
        except:
            pass
    if not loaded:
        av = Image.new("RGBA", (radius*2, radius*2), color + (255,))
        av_draw = ImageDraw.Draw(av)
        font = load_font(radius - 4, bold=True)
        av_draw.text((radius, radius), initials, font=font, fill=(255,255,255,255), anchor="mm")
        img.paste(av, (center_x - radius, center_y - radius), mask)

def draw_bar(draw, x, y, w, h, pct, color):
    draw.rectangle([x, y, x + w, y + h], fill=(26, 43, 53))
    fill_w = int(w * pct)
    if fill_w > 0:
        draw.rectangle([x, y, x + fill_w, y + h], fill=color)

def generate_daily_image(date_str, day_num, entries, people, output_path):
    sorted_entries = sorted(entries, key=lambda e: score_from_reps(e["reps"]), reverse=True)
    all_people = list(people.keys())
    logged_numbers = [e["phone"] for e in sorted_entries]
    skipped = [p for p in all_people if p not in logged_numbers]
    
    rows = len(sorted_entries) + len(skipped)
    header_h = 130
    row_h = 90
    footer_h = 80
    padding = 20
    total_h = header_h + (rows * row_h) + footer_h + padding

    img = Image.new("RGB", (CARD_W, total_h), BG_COLOR)
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, CARD_W, header_h], fill=DAILY_COLOR)

    f_label = load_font(18, bold=True)
    f_date = load_font(36, bold=True)
    f_sub = load_font(22)
    f_badge = load_font(20, bold=True)

    draw.text((30, 22), "DAILY RECAP", font=f_label, fill=GREEN_ACCENT)
    draw.text((30, 48), date_str, font=f_date, fill=TEXT_PRIMARY)
    participation = len(sorted_entries)
    total_people = len(people)
    draw.text((30, 95), f"Day {day_num}  ·  {participation} of {total_people} logged", font=f_sub, fill=(163, 217, 184))

    badge_text = f"Day {day_num}"
    bbox = draw.textbbox((0,0), badge_text, font=f_badge)
    bw = bbox[2] - bbox[0] + 28
    bh = bbox[3] - bbox[1] + 12
    bx = CARD_W - bw - 30
    by = 40
    draw_rounded_rect(draw, [bx, by, bx+bw, by+bh], 10, GREEN_ACCENT)
    draw.text((bx + 14, by + 6), badge_text, font=f_badge, fill=(15, 60, 30))

    draw.rectangle([30, header_h - 1, CARD_W - 30, header_h], fill=(31, 58, 42))

    f_name = load_font(28, bold=True)
    f_meta = load_font(20)
    f_pts = load_font(32, bold=True)
    f_pts_label = load_font(18)
    f_rank = load_font(26, bold=True)

    max_score = max((score_from_reps(e["reps"]) for e in sorted_entries), default=1)
    if max_score == 0:
        max_score = 1

    for i, entry in enumerate(sorted_entries):
        y = header_h + i * row_h
        row_color = (20, 38, 52) if i % 2 == 0 else ROW_BG
        draw.rectangle([0, y, CARD_W, y + row_h], fill=row_color)

        rank_color = RANK_COLORS[i] if i < 3 else TEXT_MUTED
        draw.text((28, y + row_h//2), str(i+1), font=f_rank, fill=rank_color, anchor="lm")

        phone = entry["phone"]
        person = people.get(phone, {})
        name = person.get("name", "Unknown")
        photo = person.get("photo", "")
        photo_path = os.path.join("photos", photo) if photo else None
        initials = "".join(w[0].upper() for w in name.split()[:2])
        av_colors = [(42,125,225),(225,84,42),(155,42,225),(225,168,42),(42,225,138)]
        av_color = av_colors[i % len(av_colors)]

        draw_avatar(img, 90, y + row_h//2, 32, photo_path, initials, av_color)

        draw.text((140, y + 18), name, font=f_name, fill=TEXT_PRIMARY)
        time_str = entry.get("time_str", "")
        draw.text((140, y + 52), f"Logged {time_str}", font=f_meta, fill=TEXT_MUTED)

        bar_x = 140
        bar_y = y + 78
        bar_w = 420
        pct = score_from_reps(entry["reps"]) / max_score
        draw_bar(draw, bar_x, bar_y, bar_w, 5, pct, rank_color)

        pts = score_from_reps(entry["reps"])
        pts_str = str(pts)
        draw.text((CARD_W - 160, y + row_h//2 - 14), pts_str, font=f_pts, fill=TEXT_PRIMARY, anchor="rm")
        draw.text((CARD_W - 155, y + row_h//2 - 14), "pts", font=f_pts_label, fill=TEXT_MUTED, anchor="lm")
        draw.text((CARD_W - 160, y + row_h//2 + 18), f"{entry['reps']} reps", font=f_meta, fill=TEXT_MUTED, anchor="rm")

    for j, phone in enumerate(skipped):
        i = len(sorted_entries) + j
        y = header_h + i * row_h
        row_color = (20, 38, 52) if i % 2 == 0 else ROW_BG
        draw.rectangle([0, y, CARD_W, y + row_h - 1], fill=row_color)

        person = people.get(phone, {})
        name = person.get("name", "Unknown")
        photo = person.get("photo", "")
        photo_path = os.path.join("photos", photo) if photo else None
        initials = "".join(w[0].upper() for w in name.split()[:2])

        draw_avatar(img, 90, y + row_h//2, 32, photo_path, initials, (60, 80, 90))

        skip_name = ImageDraw.Draw(img)
        faded_name = load_font(28, bold=True)
        draw.text((28, y + row_h//2), str(i+1), font=f_rank, fill=(40, 60, 75), anchor="lm")
        draw.text((140, y + 26), name, font=faded_name, fill=(70, 100, 115), anchor="lm")
        draw.text((140, y + 56), "No log today", font=f_meta, fill=(50, 75, 90), anchor="lm")

        pill_x = CARD_W - 170
        pill_y = y + 30
        draw_rounded_rect(draw, [pill_x, pill_y, pill_x+110, pill_y+36], 8, (20, 44, 58))
        draw.text((pill_x + 55, pill_y + 18), "skipped", font=f_meta, fill=(58, 90, 110), anchor="mm")

    fy = header_h + rows * row_h
    draw.rectangle([0, fy, CARD_W, fy + footer_h], fill=(10, 16, 24))

    total_reps = sum(e["reps"] for e in sorted_entries)
    avg_reps = total_reps // len(sorted_entries) if sorted_entries else 0
    part_pct = f"{int(len(sorted_entries)/len(people)*100)}%"
    first_log = min((e.get("time_str","") for e in sorted_entries), default="—")

    stats = [
        (str(total_reps), "Total reps"),
        (str(avg_reps), "Avg reps"),
        (part_pct, "Participation"),
        (first_log, "First log"),
    ]
    f_stat_val = load_font(26, bold=True)
    f_stat_label = load_font(17)
    col_w = CARD_W // len(stats)
    for si, (val, label) in enumerate(stats):
        cx = col_w * si + col_w // 2
        draw.text((cx, fy + 22), val, font=f_stat_val, fill=TEXT_PRIMARY, anchor="mt")
        draw.text((cx, fy + 54), label, font=f_stat_label, fill=(58, 90, 110), anchor="mt")

    img.save(output_path)
    return output_path


def generate_weekly_image(week_num, date_range_str, weekly_data, people, output_path):
    rows = len(people)
    header_h = 130
    row_h = 90
    footer_h = 80
    padding = 20
    total_h = header_h + (rows * row_h) + footer_h + padding

    img = Image.new("RGB", (CARD_W, total_h), BG_COLOR)
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, CARD_W, header_h], fill=WEEKLY_COLOR)

    f_label = load_font(18, bold=True)
    f_date = load_font(36, bold=True)
    f_sub = load_font(22)
    f_badge = load_font(20, bold=True)

    draw.text((30, 22), "WEEKLY RECAP", font=f_label, fill=BLUE_ACCENT)
    draw.text((30, 48), f"Week {week_num}", font=f_date, fill=TEXT_PRIMARY)
    draw.text((30, 95), date_range_str + "  ·  " + str(len(people)) + " players", font=f_sub, fill=(163, 184, 217))

    badge_text = f"Week {week_num}"
    bbox = draw.textbbox((0,0), badge_text, font=f_badge)
    bw = bbox[2] - bbox[0] + 28
    bh = bbox[3] - bbox[1] + 12
    bx = CARD_W - bw - 30
    by = 40
    draw_rounded_rect(draw, [bx, by, bx+bw, by+bh], 10, BLUE_ACCENT)
    draw.text((bx + 14, by + 6), badge_text, font=f_badge, fill=(7, 16, 48))

    draw.rectangle([30, header_h - 1, CARD_W - 30, header_h], fill=(31, 47, 74))

    f_name = load_font(28, bold=True)
    f_meta = load_font(20)
    f_pts = load_font(32, bold=True)
    f_pts_label = load_font(18)
    f_rank = load_font(26, bold=True)

    sorted_weekly = sorted(weekly_data.items(), key=lambda x: x[1]["total_pts"], reverse=True)
    max_pts = sorted_weekly[0][1]["total_pts"] if sorted_weekly else 1
    if max_pts == 0:
        max_pts = 1

    for i, (phone, data) in enumerate(sorted_weekly):
        y = header_h + i * row_h
        row_color = (20, 38, 52) if i % 2 == 0 else ROW_BG
        draw.rectangle([0, y, CARD_W, y + row_h], fill=row_color)

        rank_color = RANK_COLORS[i] if i < 3 else TEXT_MUTED
        draw.text((28, y + row_h//2), str(i+1), font=f_rank, fill=rank_color, anchor="lm")

        person = people.get(phone, {})
        name = person.get("name", "Unknown")
        photo = person.get("photo", "")
        photo_path = os.path.join("photos", photo) if photo else None
        initials = "".join(w[0].upper() for w in name.split()[:2])
        av_colors = [(42,125,225),(225,84,42),(155,42,225),(225,168,42),(42,225,138)]
        av_color = av_colors[i % len(av_colors)]

        draw_avatar(img, 90, y + row_h//2, 32, photo_path, initials, av_color)

        days_logged = data.get("days_logged", 0)
        best_day = data.get("best_day", 0)
        draw.text((140, y + 18), name, font=f_name, fill=TEXT_PRIMARY)
        draw.text((140, y + 52), f"{days_logged}/7 days  ·  best day {best_day} reps", font=f_meta, fill=TEXT_MUTED)

        pct = data["total_pts"] / max_pts
        draw_bar(draw, 140, y + 78, 420, 5, pct, rank_color)

        pts = data["total_pts"]
        total_reps = data.get("total_reps", 0)
        draw.text((CARD_W - 160, y + row_h//2 - 14), str(pts), font=f_pts, fill=TEXT_PRIMARY, anchor="rm")
        draw.text((CARD_W - 155, y + row_h//2 - 14), "pts", font=f_pts_label, fill=TEXT_MUTED, anchor="lm")
        draw.text((CARD_W - 160, y + row_h//2 + 18), f"{total_reps} reps total", font=f_meta, fill=TEXT_MUTED, anchor="rm")

    fy = header_h + rows * row_h
    draw.rectangle([0, fy, CARD_W, fy + footer_h], fill=(8, 12, 20))

    grand_reps = sum(d["total_reps"] for _, d in sorted_weekly)
    avg_per_person = grand_reps // len(sorted_weekly) if sorted_weekly else 0
    avg_days = sum(d["days_logged"] for _, d in sorted_weekly) / len(sorted_weekly) if sorted_weekly else 0
    top_name = people.get(sorted_weekly[0][0], {}).get("name", "—") if sorted_weekly else "—"

    stats = [
        (f"{grand_reps:,}", "Total reps"),
        (str(avg_per_person), "Avg/person"),
        (f"{avg_days:.1f}/7", "Avg days logged"),
        (top_name, "Top performer"),
    ]
    f_stat_val = load_font(26, bold=True)
    f_stat_label = load_font(17)
    col_w = CARD_W // len(stats)
    for si, (val, label) in enumerate(stats):
        cx = col_w * si + col_w // 2
        draw.text((cx, fy + 22), val, font=f_stat_val, fill=TEXT_PRIMARY, anchor="mt")
        draw.text((cx, fy + 54), label, font=f_stat_label, fill=(58, 90, 110), anchor="mt")

    img.save(output_path)
    return output_path
