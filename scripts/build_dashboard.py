"""Build the habit-challenge dashboard page (docs/index.html).

Fetches every day from the Notion database, applies each habit's own completion
rule, and writes a self-contained static page. No secrets reach the page.

Each habit has a rule, edit these freely:
  ("daily",  None)  -> must be done every day; streak counts in days.
  ("weekly", N)     -> N days within each Mon-Sun week; streak counts in weeks.
Partial first/last weeks have their target prorated so a short edge week isn't
an automatic miss. The in-progress day or week never breaks a streak.

Token: env var NOTION_TOKEN (used by GitHub Actions), otherwise the local file
notion_habit_tracker_token.txt in the project root.
"""

import calendar
import html
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

NOTION_VERSION = "2026-03-11"
DATA_SOURCE_ID = "b7f558a1-fd72-4b0c-a973-14c738d4bfe6"
TIMEZONE = timezone(timedelta(hours=5, minutes=30))  # IST, fixed offset, no DST
START = date(2026, 10, 1)
END = date(2026, 12, 31)

# name, color, priority (featured wide), rule
HABITS = [
    {"name": "Gym",       "color": "#ff6b4a", "priority": True,  "rule": ("weekly", 5)},
    {"name": "No Sugar",  "color": "#ffd23f", "priority": True,  "rule": ("weekly", 6)},
    {"name": "Good Diet", "color": "#4ade80", "priority": False, "rule": ("weekly", 5)},
    {"name": "Water",     "color": "#38bdf8", "priority": False, "rule": ("daily",  None)},
    {"name": "Abs",       "color": "#f472b6", "priority": False, "rule": ("weekly", 4)},
    {"name": "Jaw Line",  "color": "#a78bfa", "priority": False, "rule": ("weekly", 4)},
]

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent if SCRIPT_DIR.name == "scripts" else SCRIPT_DIR
OUTPUT_FILE = PROJECT_ROOT / "docs" / "index.html"


def read_token():
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if token:
        return token
    token_file = PROJECT_ROOT / "notion_habit_tracker_token.txt"
    if token_file.is_file():
        return token_file.read_text(encoding="utf-8-sig").strip()
    raise RuntimeError("Set NOTION_TOKEN or put the token in notion_habit_tracker_token.txt")


def notion(token, endpoint, payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        "https://api.notion.com/v1/" + endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_days(token):
    days, cursor = {}, None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        response = notion(token, f"data_sources/{DATA_SOURCE_ID}/query", payload)
        for page in response["results"]:
            props = page["properties"]
            stamp = props["Date"]["date"]
            if not stamp:
                continue
            day = date.fromisoformat(stamp["start"][:10])
            note = "".join(part["plain_text"] for part in props["Notes"]["rich_text"])
            days[day] = {
                "note": note,
                "habits": {habit["name"]: props[habit["name"]]["checkbox"] for habit in HABITS},
            }
        if not response["has_more"]:
            return days
        cursor = response["next_cursor"]


def checked(days, day, name):
    return bool(days.get(day, {}).get("habits", {}).get(name))


def current_streak(done, anchor):
    day = anchor if anchor in done else anchor - timedelta(days=1)
    streak = 0
    while day >= START and day in done:
        streak += 1
        day -= timedelta(days=1)
    return streak


def longest_streak(done, elapsed):
    best = run = 0
    for day in elapsed:
        run = run + 1 if day in done else 0
        best = max(best, run)
    return best


def daily_stats(days, name, elapsed, anchor):
    done = {day for day in elapsed if checked(days, day, name)}
    return {
        "type": "daily",
        "current": current_streak(done, anchor),
        "longest": longest_streak(done, elapsed),
        "done": len(done),
        "rate": round(100 * len(done) / len(elapsed)) if elapsed else 0,
        "strip": [(day, day in done) for day in elapsed[-14:]],
    }


def weekly_stats(days, name, target, today):
    weeks = []
    week_start = START - timedelta(days=START.weekday())  # Monday on/before Oct 1
    while week_start <= END:
        week_end = week_start + timedelta(days=6)
        in_challenge = [week_start + timedelta(days=i) for i in range(7)
                        if START <= week_start + timedelta(days=i) <= END]
        if in_challenge and week_start <= today:
            target_eff = max(1, round(target * len(in_challenge) / 7))
            done = sum(1 for day in in_challenge if day <= today and checked(days, day, name))
            if week_end < today:
                status = "met" if done >= target_eff else "missed"
            else:
                status = "met" if done >= target_eff else "current"
            weeks.append({"start": week_start, "end": week_end, "done": done,
                          "target": target_eff, "status": status,
                          "current": week_start <= today <= week_end})
        week_start += timedelta(days=7)

    current = 0
    for week in reversed(weeks):
        if week["status"] == "met":
            current += 1
        elif week["status"] == "current":
            continue
        else:
            break

    best = run = 0
    for week in weeks:
        if week["status"] == "met":
            run += 1
            best = max(best, run)
        elif week["status"] != "current":
            run = 0

    this = next((week for week in weeks if week["current"]), None)
    finished = [week for week in weeks if not week["current"]]
    days_left = max(0, (min(this["end"], END) - today).days) if this else 0
    return {
        "type": "weekly",
        "current": current,
        "longest": best,
        "this_done": this["done"] if this else 0,
        "this_target": this["target"] if this else target,
        "days_left": days_left,
        "weeks_met": sum(1 for week in finished if week["status"] == "met"),
        "weeks_total": len(finished),
        "recent": [week["status"] for week in weeks[-8:]],
    }


def habit_stats(days, elapsed, anchor, today):
    stats = []
    for habit in HABITS:
        kind, target = habit["rule"]
        data = (daily_stats(days, habit["name"], elapsed, anchor) if kind == "daily"
                else weekly_stats(days, habit["name"], target, today))
        stats.append({**habit, **data})
    return stats


def count_color(count, total, is_future):
    if is_future:
        return "transparent"
    if count == 0:
        return "#1b2130"
    shades = ["#14532d", "#166534", "#15803d", "#22c55e", "#4ade80"]
    return shades[min(len(shades) - 1, round(count / total * (len(shades) - 1)))]


def render_calendar(days, today, total):
    blocks = []
    for month in (10, 11, 12):
        first = date(2026, month, 1)
        cells = ['<span class="pad"></span>'] * first.weekday()
        for number in range(1, calendar.monthrange(2026, month)[1] + 1):
            day = date(2026, month, number)
            done = [habit["name"] for habit in HABITS if checked(days, day, habit["name"])]
            is_future = day > today
            classes = "cell" + (" today" if day == today else "") + (" future" if is_future else "")
            tip = f"{day.isoformat()} · {', '.join(done) if done else 'none'}"
            style = f"background:{count_color(len(done), total, is_future)}"
            cells.append(f'<span class="{classes}" style="{style}" title="{html.escape(tip)}"></span>')
        weekdays = "".join(f'<span class="wd">{d}</span>' for d in "MTWTFSS")
        blocks.append(
            f'<div class="month"><div class="mname">{first.strftime("%B")}</div>'
            f'<div class="grid"><div class="wdrow">{weekdays}</div>{"".join(cells)}</div></div>'
        )
    return "".join(blocks)


def card_shell(stat, inner):
    tag = '<span class="tag">priority</span>' if stat["priority"] else ""
    big = " big" if stat["priority"] else ""
    return (f'<div class="card{big}" style="--c:{stat["color"]}">'
            f'<div class="chead"><span class="cname">{stat["name"]}</span>{tag}</div>'
            f'{inner}</div>')


def render_daily(stat):
    dots = "".join(
        f'<span class="dot" style="background:{stat["color"] if done else "#232a39"}" '
        f'title="{day.isoformat()}"></span>'
        for day, done in stat["strip"]
    )
    inner = (f'<div class="streak">{stat["current"]}<span class="unit">day streak</span></div>'
             f'<div class="sub"><span>Longest <b>{stat["longest"]}</b></span>'
             f'<span>Done <b>{stat["done"]}</b></span>'
             f'<span>Rate <b>{stat["rate"]}%</b></span></div>'
             f'<div class="strip">{dots}</div>')
    return card_shell(stat, inner)


def render_weekly(stat):
    boxes = []
    for status in stat["recent"]:
        if status == "met":
            style = f"background:{stat['color']}"
        elif status == "current":
            style = "background:transparent;border:1px dashed #4a5568"
        else:
            style = "background:#2a3344"
        boxes.append(f'<span class="wkbox" style="{style}"></span>')
    this = f'{stat["this_done"]}/{stat["this_target"]}'
    left = f' · {stat["days_left"]}d left' if stat["days_left"] else ""
    inner = (f'<div class="streak">{stat["current"]}<span class="unit">week streak</span></div>'
             f'<div class="sub"><span>This week <b>{this}</b>{left}</span>'
             f'<span>Longest <b>{stat["longest"]}w</b></span>'
             f'<span>Weeks met <b>{stat["weeks_met"]}/{stat["weeks_total"]}</b></span></div>'
             f'<div class="strip">{"".join(boxes)}</div>')
    return card_shell(stat, inner)


def render_notes(days, elapsed):
    recent = [(day, days[day]["note"]) for day in reversed(elapsed)
              if day in days and days[day]["note"]][:5]
    if not recent:
        return ""
    items = "".join(
        f'<li><span class="ndate">{day:%b} {day.day}</span>{html.escape(note)}</li>'
        for day, note in recent
    )
    return f'<section class="notes"><h2>Recent notes</h2><ul>{items}</ul></section>'


def build():
    token = read_token()
    days = fetch_days(token)
    now = datetime.now(TIMEZONE)
    today = now.date()
    anchor = min(today, END)
    last = min(today, END)
    elapsed = [START + timedelta(days=i) for i in range((last - START).days + 1)] if today >= START else []

    stats = habit_stats(days, elapsed, anchor, today)
    cards = "".join(render_daily(stat) if stat["type"] == "daily" else render_weekly(stat) for stat in stats)

    day_number = len(elapsed)
    total_days = (END - START).days + 1
    remaining = max(0, (END - today).days)
    progress = round(100 * day_number / total_days)

    today_done = [habit["name"] for habit in HABITS if checked(days, today, habit["name"])]
    chips = "".join(
        f'<span class="chip" style="--c:{habit["color"]}{"" if habit["name"] in today_done else ";opacity:.25"}">{habit["name"]}</span>'
        for habit in HABITS
    )

    page = PAGE_TEMPLATE.format(
        updated=f"{now:%b} {now.day}, {now.year} · {now.hour % 12 or 12}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'} IST",
        day_number=day_number,
        total_days=total_days,
        remaining=remaining,
        progress=progress,
        chips=chips,
        cards=cards,
        calendar=render_calendar(days, today, len(HABITS)),
        notes=render_notes(days, elapsed),
    )
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(page, encoding="utf-8")
    print(f"Wrote {OUTPUT_FILE} — day {day_number}/{total_days}, {remaining} left.")


PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Challenge</title>
<style>
:root {{ color-scheme: dark; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  background: radial-gradient(1200px 600px at 20% -10%, #15203a 0%, #0b0e14 55%) #0b0e14;
  color: #e6e9ef; min-height: 100vh; padding: 40px 20px 60px;
}}
.wrap {{ max-width: 960px; margin: 0 auto; }}
header {{ display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 10px; }}
h1 {{ font-size: 1.9rem; letter-spacing: -.02em; }}
.updated {{ color: #8b93a7; font-size: .8rem; }}
.progress {{ margin: 22px 0 30px; }}
.pbar {{ height: 10px; border-radius: 99px; background: #1b2130; overflow: hidden; }}
.pfill {{ height: 100%; border-radius: 99px; background: linear-gradient(90deg, #ff6b4a, #ffd23f, #4ade80); }}
.pmeta {{ display: flex; justify-content: space-between; margin-top: 8px; color: #8b93a7; font-size: .85rem; }}
.pmeta b {{ color: #e6e9ef; }}
.today {{ margin-bottom: 30px; }}
.today h2, section h2 {{ font-size: .8rem; text-transform: uppercase; letter-spacing: .08em; color: #8b93a7; margin-bottom: 12px; }}
.chips {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.chip {{ font-size: .85rem; padding: 6px 12px; border-radius: 99px; border: 1px solid var(--c); color: var(--c); }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 14px; margin-bottom: 36px; }}
.card {{ background: #141924; border: 1px solid #222a39; border-radius: 16px; padding: 18px; position: relative; overflow: hidden; }}
.card::before {{ content: ""; position: absolute; inset: 0 0 auto 0; height: 3px; background: var(--c); }}
.card.big {{ grid-column: span 2; }}
.chead {{ display: flex; align-items: center; justify-content: space-between; }}
.cname {{ font-weight: 600; }}
.tag {{ font-size: .62rem; text-transform: uppercase; letter-spacing: .08em; color: var(--c); border: 1px solid var(--c); border-radius: 99px; padding: 2px 7px; }}
.streak {{ font-size: 2.8rem; font-weight: 700; color: var(--c); line-height: 1; margin: 14px 0 4px; display: flex; align-items: baseline; gap: 8px; }}
.unit {{ font-size: .75rem; font-weight: 500; color: #8b93a7; }}
.sub {{ display: flex; gap: 14px; flex-wrap: wrap; color: #8b93a7; font-size: .8rem; margin-bottom: 14px; }}
.sub b {{ color: #e6e9ef; }}
.strip {{ display: flex; gap: 3px; }}
.dot {{ width: 100%; height: 14px; border-radius: 3px; }}
.wkbox {{ width: 100%; height: 14px; border-radius: 3px; }}
.calendar {{ margin-bottom: 36px; }}
.months {{ display: flex; flex-wrap: wrap; gap: 26px; }}
.month .mname {{ font-size: .85rem; color: #8b93a7; margin-bottom: 8px; }}
.grid {{ display: grid; grid-template-columns: repeat(7, 16px); gap: 4px; }}
.wdrow {{ display: contents; }}
.wd {{ font-size: .6rem; color: #5a6274; text-align: center; }}
.cell {{ width: 16px; height: 16px; border-radius: 4px; }}
.cell.future {{ border: 1px dashed #2a3344; }}
.cell.today {{ box-shadow: 0 0 0 2px #e6e9ef; }}
.pad {{ width: 16px; height: 16px; }}
.legend {{ display: flex; align-items: center; gap: 6px; margin-top: 14px; color: #8b93a7; font-size: .75rem; }}
.legend span.box {{ width: 14px; height: 14px; border-radius: 3px; }}
.notes ul {{ list-style: none; display: grid; gap: 8px; }}
.notes li {{ background: #141924; border: 1px solid #222a39; border-radius: 10px; padding: 10px 14px; font-size: .9rem; }}
.ndate {{ color: #8b93a7; font-size: .78rem; margin-right: 10px; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>3-Month Challenge</h1>
    <span class="updated">Updated {updated}</span>
  </header>

  <div class="progress">
    <div class="pbar"><div class="pfill" style="width:{progress}%"></div></div>
    <div class="pmeta"><span>Day <b>{day_number}</b> of {total_days}</span><span><b>{remaining}</b> days left</span></div>
  </div>

  <div class="today">
    <h2>Today</h2>
    <div class="chips">{chips}</div>
  </div>

  <div class="cards">{cards}</div>

  <section class="calendar">
    <h2>Habits completed per day</h2>
    <div class="months">{calendar}</div>
    <div class="legend">
      <span>fewer</span>
      <span class="box" style="background:#1b2130"></span>
      <span class="box" style="background:#166534"></span>
      <span class="box" style="background:#15803d"></span>
      <span class="box" style="background:#22c55e"></span>
      <span class="box" style="background:#4ade80"></span>
      <span>more</span>
    </div>
  </section>

  {notes}
</div>
</body>
</html>
"""


if __name__ == "__main__":
    build()
