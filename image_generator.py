"""
image_generator.py — Pushup Challenge Recap Card Generator
Dynamic height portrait canvas, dark sports-app aesthetic
"""

from PIL import Image, ImageDraw, ImageFont
from datetime import date
import math, os

W = 1080
PADDING = 36

BG         = (11, 13, 17)
HDR_GREEN  = (13, 48, 26)
HDR_BLUE   = (10, 28, 60)
ACC_GREEN  = (34, 197, 94)
ACC_BLUE   = (59, 130, 246)
ROW_A      = (20, 24, 31)
ROW_B      = (16, 19, 25)
ROW_SKIP   = (14, 16, 21)
GOLD       = (255, 196, 0)
SILVER     = (200, 200, 210)
BRONZE     = (188, 120, 60)
DIM        = (55, 62, 75)
TEXT_PRI   = (235, 238, 245)
TEXT_SEC   = (110, 120, 140)
TEXT_SKIP  = (50, 56, 68)
DIVIDER    = (28, 33, 42)
FOOTER_BG  = (15, 18, 23)

AVATAR_COLORS = [
    (34, 197, 94),(59, 130, 246),(251, 146, 60),(168, 85, 247),
    (239, 68, 68),(20, 184, 166),(234, 179, 8),(236, 72, 153),
    (99, 102, 241),(132, 204, 22),
]

def _fonts():
    base = '/usr/share/fonts/truetype/dejavu/DejaVuSans'
    try:
        return {
            'bold':    ImageFont.truetype(f'{base}-Bold.ttf', 28),
            'med':     ImageFont.truetype(f'{base}.ttf', 24),
            'sm':      ImageFont.truetype(f'{base}.ttf', 20),
            'xs':      ImageFont.truetype(f'{base}.ttf', 17),
            'rank':    ImageFont.truetype(f'{base}-Bold.ttf', 36),
            'pts':     ImageFont.truetype(f'{base}-Bold.ttf', 52),
            'pts_sm':  ImageFont.truetype(f'{base}-Bold.ttf', 24),
            'hdr':     ImageFont.truetype(f'{base}-Bold.ttf', 52),
            'hdr_m':   ImageFont.truetype(f'{base}.ttf', 22),
            'pill':    ImageFont.truetype(f'{base}-Bold.ttf', 19),
            'name':    ImageFont.truetype(f'{base}-Bold.ttf', 32),
            'rep_sub': ImageFont.truetype(f'{base}.ttf', 20),
            'col':     ImageFont.truetype(f'{base}-Bold.ttf', 16),
            'bar':     ImageFont.truetype(f'{base}.ttf', 15),
        }
    except:
        d = ImageFont.load_default()
        return {k: d for k in ['bold','med','sm','xs','rank','pts','pts_sm',
                                'hdr','hdr_m','pill','name','rep_sub','col','bar']}

def calculate_points(reps):
    if reps <= 0:   return 0
    if reps <= 100: return int(reps)
    if reps <= 150: return int(100 + (reps - 100) * 0.5)
    if reps <= 200: return int(100 + 25 + (reps - 150) * 0.25)
    return 150

def _rank_color(rank):
    return [GOLD, SILVER, BRONZE][rank - 1] if rank <= 3 else DIM

def _initials(name):
    parts = name.split()
    return (parts[0][0] + parts[-1][0]).upper() if len(parts) > 1 else parts[0][:2].upper()

def _draw_header(draw, f, hdr_color, accent, label, date_line1, date_line2, badge_text, canvas_h):
    HDR_H = 195
    draw.rectangle([0, 0, W, HDR_H], fill=hdr_color)
    draw.rectangle([0, HDR_H - 4, W, HDR_H], fill=accent)
    # pill
    pw = draw.textlength(label, font=f['pill'])
    px, py = PADDING, 28
    draw.rounded_rectangle([px-12, py-7, px+pw+12, py+26], radius=14, fill=accent)
    draw.text((px, py), label, font=f['pill'], fill=(0, 0, 0))
    # badge top right
    bw = draw.textlength(badge_text, font=f['pill'])
    bx = W - PADDING - bw - 24
    draw.rounded_rectangle([bx-12, py-7, bx+bw+12, py+26], radius=14, outline=accent, width=2)
    draw.text((bx, py), badge_text, font=f['pill'], fill=accent)
    # date
    draw.text((PADDING, 70), date_line1, font=f['hdr'], fill=TEXT_PRI)
    draw.text((PADDING, 135), date_line2, font=f['hdr_m'], fill=TEXT_SEC)
    return HDR_H

def _draw_col_headers(draw, f, y, show_reps_bar=False):
    COL_H = 38
    draw.rectangle([0, y, W, y + COL_H], fill=(17, 20, 27))
    draw.text((PADDING, y + 10), '#', font=f['col'], fill=TEXT_SEC)
    draw.text((PADDING + 130, y + 10), 'PLAYER', font=f['col'], fill=TEXT_SEC)
    if show_reps_bar:
        draw.text((W - PADDING - 280, y + 10), 'REPS', font=f['col'], fill=TEXT_SEC)
    draw.text((W - PADDING - 60, y + 10), 'PTS', font=f['col'], fill=TEXT_SEC)
    return COL_H

def _draw_player_row(draw, f, ry, row_h, rank, orig_idx, first_name, initials,
                     pts, reps, sub_line=None, accent=ACC_GREEN):
    bg = ROW_A if rank % 2 == 1 else ROW_B
    draw.rectangle([0, ry, W, ry + row_h], fill=bg)
    if rank <= 3:
        draw.rectangle([0, ry, 5, ry + row_h], fill=_rank_color(rank))
    # rank number
    rc = _rank_color(rank)
    rstr = str(rank)
    rw = draw.textlength(rstr, font=f['rank'])
    draw.text((PADDING + (30 - rw) // 2, ry + row_h // 2 - 22), rstr, font=f['rank'], fill=rc)
    # avatar
    avc = AVATAR_COLORS[orig_idx % len(AVATAR_COLORS)]
    avcx = PADDING + 70 + 36
    draw.ellipse([avcx-36, ry+row_h//2-36, avcx+36, ry+row_h//2+36], fill=avc)
    iw = draw.textlength(initials, font=f['sm'])
    draw.text((avcx - iw/2, ry + row_h//2 - 12), initials, font=f['sm'], fill=(255,255,255))
    # name
    draw.text((avcx + 54, ry + row_h//2 - 28), first_name, font=f['name'], fill=TEXT_PRI)
    # sub line (reps for daily, days for weekly)
    if sub_line:
        draw.text((avcx + 56, ry + row_h//2 + 10), sub_line, font=f['xs'], fill=TEXT_SEC)
    # pts big right
    pts_str = str(pts)
    ptw = draw.textlength(pts_str, font=f['pts'])
    draw.text((W - PADDING - ptw, ry + row_h//2 - 28), pts_str, font=f['pts'], fill=TEXT_PRI)
    ptlw = draw.textlength('pts', font=f['xs'])
    draw.text((W - PADDING - ptlw, ry + row_h//2 + 26), 'pts', font=f['xs'], fill=TEXT_SEC)
    # divider
    draw.rectangle([0, ry + row_h - 1, W, ry + row_h], fill=DIVIDER)

def _draw_weekly_row(draw, f, ry, row_h, rank, orig_idx, first_name, initials,
                     pts, reps, days, accent=ACC_BLUE):
    bg = ROW_A if rank % 2 == 1 else ROW_B
    draw.rectangle([0, ry, W, ry + row_h], fill=bg)
    if rank <= 3:
        draw.rectangle([0, ry, 5, ry + row_h], fill=_rank_color(rank))
    rc = _rank_color(rank)
    rstr = str(rank)
    rw = draw.textlength(rstr, font=f['rank'])
    draw.text((PADDING + (30 - rw) // 2, ry + row_h//2 - 22), rstr, font=f['rank'], fill=rc)
    avc = AVATAR_COLORS[orig_idx % len(AVATAR_COLORS)]
    avcx = PADDING + 70 + 36
    draw.ellipse([avcx-36, ry+row_h//2-36, avcx+36, ry+row_h//2+36], fill=avc)
    iw = draw.textlength(initials, font=f['sm'])
    draw.text((avcx - iw/2, ry + row_h//2 - 12), initials, font=f['sm'], fill=(255,255,255))
    draw.text((avcx + 54, ry + row_h//2 - 28), first_name, font=f['name'], fill=TEXT_PRI)
    draw.text((avcx + 56, ry + row_h//2 + 10), f'{days}/7 days', font=f['xs'], fill=TEXT_SEC)
    # reps + progress bar
    bar_x = W - PADDING - 310
    bar_w = 120
    reps_str = str(reps)
    repsw = draw.textlength(reps_str, font=f['pts_sm'])
    draw.text((bar_x + (bar_w - repsw)//2, ry + row_h//2 - 22), reps_str, font=f['pts_sm'], fill=TEXT_SEC)
    bar_y = ry + row_h//2 + 8
    pct = min(reps / 1400, 1.0)
    draw.rounded_rectangle([bar_x, bar_y, bar_x+bar_w, bar_y+6], radius=3, fill=(35,40,50))
    if pct > 0:
        draw.rounded_rectangle([bar_x, bar_y, bar_x+int(bar_w*pct), bar_y+6], radius=3, fill=accent)
    draw.text((bar_x, bar_y + 10), f'{reps}/1400', font=f['bar'], fill=DIM)
    # pts
    pts_str = str(pts)
    ptw = draw.textlength(pts_str, font=f['pts'])
    draw.text((W - PADDING - ptw, ry + row_h//2 - 28), pts_str, font=f['pts'], fill=TEXT_PRI)
    ptlw = draw.textlength('pts', font=f['xs'])
    draw.text((W - PADDING - ptlw, ry + row_h//2 + 26), 'pts', font=f['xs'], fill=TEXT_SEC)
    draw.rectangle([0, ry + row_h - 1, W, ry + row_h], fill=DIVIDER)

def _draw_skipped(draw, f, y, skipped_list):
    SKIP_HDR_H = 36
    SKIP_ROW_H = 80
    draw.rectangle([0, y, W, y + SKIP_HDR_H], fill=(15, 17, 22))
    draw.text((PADDING, y + 9), 'DID NOT LOG', font=f['xs'], fill=DIM)
    draw.rectangle([PADDING + 120, y + 17, W - PADDING, y + 19], fill=DIM)
    for i, (orig_idx, name) in enumerate(skipped_list):
        ry = y + SKIP_HDR_H + i * SKIP_ROW_H
        draw.rectangle([0, ry, W, ry + SKIP_ROW_H], fill=ROW_SKIP)
        parts = name.split()
        initials = _initials(name)
        avcx = PADDING + 70 + 28
        draw.ellipse([avcx-28, ry+SKIP_ROW_H//2-28, avcx+28, ry+SKIP_ROW_H//2+28], fill=(32,36,44))
        iw = draw.textlength(initials, font=f['xs'])
        draw.text((avcx - iw/2, ry + SKIP_ROW_H//2 - 10), initials, font=f['xs'], fill=TEXT_SKIP)
        draw.text((avcx + 40, ry + SKIP_ROW_H//2 - 16), parts[0], font=f['med'], fill=TEXT_SKIP)
        dash_w = draw.textlength('—', font=f['med'])
        draw.text((W - PADDING - dash_w, ry + SKIP_ROW_H//2 - 12), '—', font=f['med'], fill=TEXT_SKIP)
        draw.rectangle([0, ry + SKIP_ROW_H - 1, W, ry + SKIP_ROW_H], fill=DIVIDER)
    return SKIP_HDR_H + len(skipped_list) * SKIP_ROW_H

def _draw_footer(draw, f, fy, active, total_reps):
    FOOTER_H = 64
    draw.rectangle([0, fy, W, fy + FOOTER_H], fill=FOOTER_BG)
    draw.rectangle([0, fy, W, fy + 2], fill=DIVIDER)
    draw.text((PADDING, fy + 20), f'{active} ACTIVE', font=f['bold'], fill=TEXT_SEC)
    tr = f'Total: {total_reps} reps'
    trw = draw.textlength(tr, font=f['bold'])
    draw.text((W - PADDING - trw, fy + 20), tr, font=f['bold'], fill=TEXT_SEC)

def generate_daily_recap(people, daily_logs, target_date, day_number):
    f = _fonts()
    ROW_H = 120
    HDR_H = 195
    COL_H = 38
    FOOTER_H = 64
    SKIP_HDR_H = 36
    SKIP_ROW_H = 80

    logged = []
    skipped = []
    for i, p in enumerate(people):
        name = p['name']
        reps = daily_logs.get(name, 0)
        if reps > 0:
            logged.append((i, name, reps))
        else:
            skipped.append((i, name))
    logged.sort(key=lambda x: calculate_points(x[2]), reverse=True)

    skip_block = SKIP_HDR_H + len(skipped) * SKIP_ROW_H if skipped else 0
    total_h = HDR_H + COL_H + len(logged) * ROW_H + skip_block + FOOTER_H

    img = Image.new('RGB', (W, total_h), BG)
    draw = ImageDraw.Draw(img)

    date_line1 = target_date.strftime('%b %d').upper().lstrip('0')
    date_line2 = target_date.strftime('%A, %B %-d %Y')
    badge = f'DAY {day_number}'
    _draw_header(draw, f, HDR_GREEN, ACC_GREEN, 'DAILY RECAP', date_line1, date_line2, badge, total_h)

    cy = HDR_H
    _draw_col_headers(draw, f, cy)

    for rank, (orig_idx, name, reps) in enumerate(logged, 1):
        ry = HDR_H + COL_H + (rank - 1) * ROW_H
        pts = calculate_points(reps)
        parts = name.split()
        _draw_player_row(draw, f, ry, ROW_H, rank, orig_idx,
                         parts[0], _initials(name), pts, reps,
                         sub_line=f'{reps} reps')

    if skipped:
        sy = HDR_H + COL_H + len(logged) * ROW_H
        _draw_skipped(draw, f, sy, skipped)

    total_reps = sum(r for _, _, r in logged)
    _draw_footer(draw, f, total_h - FOOTER_H, len(logged), total_reps)

    return img

def generate_weekly_recap(people, weekly_logs, week_number, week_start, week_end):
    f = _fonts()
    ROW_H = 130
    HDR_H = 215
    COL_H = 38
    FOOTER_H = 64
    SKIP_HDR_H = 36
    SKIP_ROW_H = 80

    def wpts(name):
        d = weekly_logs.get(name, {})
        days = d.get('days', 0)
        reps = d.get('reps', 0)
        if days == 0: return 0
        avg = reps / days
        return calculate_points(int(avg)) * days

    logged = []
    skipped = []
    for i, p in enumerate(people):
        name = p['name']
        d = weekly_logs.get(name, {})
        if d.get('days', 0) > 0:
            logged.append((i, name, d.get('reps', 0), d.get('days', 0)))
        else:
            skipped.append((i, name))
    logged.sort(key=lambda x: wpts(x[1]), reverse=True)

    skip_block = SKIP_HDR_H + len(skipped) * SKIP_ROW_H if skipped else 0
    total_h = HDR_H + COL_H + len(logged) * ROW_H + skip_block + FOOTER_H

    img = Image.new('RGB', (W, total_h), BG)
    draw = ImageDraw.Draw(img)

    d1 = week_start.strftime('%b %-d').upper()
    d2 = week_end.strftime('%b %-d').upper()
    date_line1 = f'{d1} – {d2}'
    date_line2 = f'Week {week_number} of Challenge  •  Max possible: 1,050 pts'
    badge = f'WEEK {week_number}'
    _draw_header(draw, f, HDR_BLUE, ACC_BLUE, 'WEEKLY RECAP', date_line1, date_line2, badge, total_h)

    cy = HDR_H
    _draw_col_headers(draw, f, cy, show_reps_bar=True)

    for rank, (orig_idx, name, reps, days) in enumerate(logged, 1):
        ry = HDR_H + COL_H + (rank - 1) * ROW_H
        pts = wpts(name)
        parts = name.split()
        _draw_weekly_row(draw, f, ry, ROW_H, rank, orig_idx,
                         parts[0], _initials(name), int(pts), reps, days)

    if skipped:
        sy = HDR_H + COL_H + len(logged) * ROW_H
        _draw_skipped(draw, f, sy, skipped)

    total_reps = sum(r for _, _, r, _ in logged)
    _draw_footer(draw, f, total_h - FOOTER_H, len(logged), total_reps)

    return img

if __name__ == '__main__':
    from datetime import date
    people = [
        {'name': 'Vincent Andreozzi'},
        {'name': 'Jake Nic'},
        {'name': 'Marcus Webb'},
        {'name': 'Chris Donovan'},
        {'name': 'Tyler Brooks'},
        {'name': 'Liam Torres'},
        {'name': 'Noah Patel'},
        {'name': 'Ethan Cruz'},
    ]
    daily_logs = {
        'Vincent Andreozzi': 185,
        'Jake Nic': 142,
        'Marcus Webb': 120,
        'Chris Donovan': 95,
        'Tyler Brooks': 78,
        'Liam Torres': 60,
    }
    weekly_logs = {
        'Vincent Andreozzi': {'reps': 980, 'days': 7},
        'Jake Nic':          {'reps': 820, 'days': 6},
        'Marcus Webb':       {'reps': 700, 'days': 7},
        'Chris Donovan':     {'reps': 560, 'days': 5},
        'Tyler Brooks':      {'reps': 430, 'days': 5},
        'Liam Torres':       {'reps': 310, 'days': 4},
    }
    d = generate_daily_recap(people, daily_logs, date(2026, 5, 14), 3)
    d.save('/tmp/preview_daily.png')
    w = generate_weekly_recap(people, weekly_logs, 1,
                              date(2026, 5, 12), date(2026, 5, 18))
    w.save('/tmp/preview_weekly.png')
    print('Saved previews to /tmp/')
