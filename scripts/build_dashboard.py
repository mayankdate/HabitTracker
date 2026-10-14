"""Build the habit-challenge dashboard page (docs/index.html).

Fetches every day from the Notion database, applies each habit's own completion
rule, and writes a self-contained static page. No secrets reach the page.

Layout: a progress bar, a cumulative stats strip, then one row per habit with
its stats and its own Oct/Nov/Dec calendars.

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

# name, color, priority (starred), rule
HABITS = [
    {"name": "Gym",       "color": "#ff6b4a", "priority": True,  "rule": ("weekly", 5)},
    {"name": "No Sugar",  "color": "#ffd23f", "priority": True,  "rule": ("weekly", 6)},
    {"name": "Good Diet", "color": "#4ade80", "priority": False, "rule": ("weekly", 5)},
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
    return {"current": current_streak(done, anchor), "longest": longest_streak(done, elapsed)}


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
        "current": current, "longest": best,
        "this_done": this["done"] if this else 0,
        "this_target": this["target"] if this else target,
        "days_left": days_left,
        "weeks_met": sum(1 for week in finished if week["status"] == "met"),
        "weeks_total": len(finished),
    }


def habit_stats(days, elapsed, anchor, today):
    stats = []
    for habit in HABITS:
        kind, target = habit["rule"]
        done_total = sum(1 for day in elapsed if checked(days, day, habit["name"]))
        extra = (daily_stats(days, habit["name"], elapsed, anchor) if kind == "daily"
                 else weekly_stats(days, habit["name"], target, today))
        stats.append({
            **habit, **extra, "kind": kind,
            "done_total": done_total,
            "rate": round(100 * done_total / len(elapsed)) if elapsed else 0,
        })
    return stats


def render_month(name, color, month, days, today):
    first = date(2026, month, 1)
    cells = ['<span class="mpad"></span>'] * first.weekday()
    for number in range(1, calendar.monthrange(2026, month)[1] + 1):
        day = date(2026, month, number)
        future = day > today
        classes = "mc" + (" today" if day == today else "") + (" future" if future else "")
        background = color if checked(days, day, name) else ("transparent" if future else "#232a39")
        cells.append(f'<span class="{classes}" style="background:{background}" title="{day.isoformat()}"></span>')
    return (f'<div class="mcal"><div class="mlabel">{first:%b}</div>'
            f'<div class="mgrid">{"".join(cells)}</div></div>')


def stats_block(stat):
    if stat["kind"] == "daily":
        return (f'<div class="hbig">{stat["current"]}<span class="u">day streak</span></div>'
                f'<div class="hsub">Longest <b>{stat["longest"]}</b> · Done <b>{stat["done_total"]}</b>'
                f' · Rate <b>{stat["rate"]}%</b></div>')
    left = f' · {stat["days_left"]}d left' if stat["days_left"] else ""
    return (f'<div class="hbig">{stat["current"]}<span class="u">week streak</span></div>'
            f'<div class="hsub">This week <b>{stat["this_done"]}/{stat["this_target"]}</b>{left}<br>'
            f'Longest <b>{stat["longest"]}w</b> · Met <b>{stat["weeks_met"]}/{stat["weeks_total"]}</b>'
            f' · Rate <b>{stat["rate"]}%</b></div>')


def habit_row(stat, days, today):
    kind, target = stat["rule"]
    rule_label = "daily" if kind == "daily" else f"{target}/wk"
    star = '<span class="star">★</span>' if stat["priority"] else ""
    cals = "".join(render_month(stat["name"], stat["color"], month, days, today) for month in (10, 11, 12))
    return (f'<div class="hrow" style="--c:{stat["color"]}">'
            f'<div class="hinfo"><div class="hname">{stat["name"]}{star}'
            f'<span class="hrule">{rule_label}</span></div>{stats_block(stat)}</div>'
            f'<div class="hcals">{cals}</div></div>')


def render_cumulative(stats, elapsed, days):
    total_checks = sum(stat["done_total"] for stat in stats)
    perfect = sum(1 for day in elapsed if all(checked(days, day, habit["name"]) for habit in HABITS))
    best = max(stats, key=lambda stat: stat["rate"])
    worst = min(stats, key=lambda stat: stat["rate"])
    tiles = [
        ("", total_checks, "check-ins logged"),
        ("", perfect, f"perfect days · all {len(HABITS)}"),
        (best["color"], f'{best["rate"]}%', f'{best["name"]} · most consistent'),
        (worst["color"], f'{worst["rate"]}%', f'{worst["name"]} · needs work'),
    ]
    return "".join(
        f'<div class="tile"><div class="big"{f" style=color:{color}" if color else ""}>{value}</div>'
        f'<div class="lbl">{label}</div></div>'
        for color, value, label in tiles
    )


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
    rows = "".join(habit_row(stat, days, today) for stat in stats)

    day_number = len(elapsed)
    total_days = (END - START).days + 1
    remaining = max(0, (END - today).days)
    progress = round(100 * day_number / total_days)

    page = PAGE_TEMPLATE.format(
        updated=f"{now:%b} {now.day}, {now.year} · {now.hour % 12 or 12}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'} IST",
        day_number=day_number,
        total_days=total_days,
        remaining=remaining,
        progress=progress,
        cumulative=render_cumulative(stats, elapsed, days),
        rows=rows,
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
.wrap {{ max-width: 1040px; margin: 0 auto; }}
header {{ display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 10px; }}
h1 {{ font-size: 1.9rem; letter-spacing: -.02em; }}
.updated {{ color: #8b93a7; font-size: .8rem; }}
.progress {{ margin: 22px 0 30px; }}
.pbar {{ height: 10px; border-radius: 99px; background: #1b2130; overflow: hidden; }}
.pfill {{ height: 100%; border-radius: 99px; background: linear-gradient(90deg, #ff6b4a, #ffd23f, #4ade80); }}
.pmeta {{ display: flex; justify-content: space-between; margin-top: 8px; color: #8b93a7; font-size: .85rem; }}
.pmeta b {{ color: #e6e9ef; }}

.cum {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 20px; }}
.tile {{ background: #141924; border: 1px solid #222a39; border-radius: 14px; padding: 16px 18px; }}
.tile .big {{ font-size: 1.9rem; font-weight: 700; line-height: 1; }}
.tile .lbl {{ color: #8b93a7; font-size: .76rem; margin-top: 6px; }}

.rows {{ margin-top: 10px; }}
.hrow {{ display: flex; gap: 24px; align-items: flex-start; flex-wrap: wrap; padding: 20px 0; border-top: 1px solid #1c2330; }}
.hinfo {{ width: 190px; flex: none; position: relative; padding-left: 14px; }}
.hinfo::before {{ content: ""; position: absolute; left: 0; top: 4px; bottom: 4px; width: 3px; border-radius: 3px; background: var(--c); }}
.hname {{ font-weight: 600; font-size: 1.05rem; display: flex; align-items: center; gap: 8px; }}
.star {{ color: var(--c); font-size: .8rem; }}
.hrule {{ font-size: .66rem; color: #8b93a7; border: 1px solid #2a3344; border-radius: 99px; padding: 1px 8px; margin-left: auto; }}
.hbig {{ font-size: 2.3rem; font-weight: 700; color: var(--c); line-height: 1; margin: 12px 0 4px; }}
.hbig .u {{ font-size: .7rem; font-weight: 500; color: #8b93a7; margin-left: 7px; }}
.hsub {{ color: #8b93a7; font-size: .78rem; line-height: 1.6; }}
.hsub b {{ color: #e6e9ef; }}

.hcals {{ display: flex; gap: 20px; flex-wrap: wrap; }}
.mcal .mlabel {{ font-size: .68rem; color: #5a6274; margin-bottom: 6px; text-transform: uppercase; letter-spacing: .07em; }}
.mgrid {{ display: grid; grid-template-columns: repeat(7, 13px); gap: 3px; }}
.mc {{ width: 13px; height: 13px; border-radius: 3px; }}
.mc.future {{ border: 1px dashed #2a3344; }}
.mc.today {{ box-shadow: 0 0 0 2px #e6e9ef; }}
.mpad {{ width: 13px; height: 13px; }}

.notes {{ margin-top: 40px; }}
.notes h2 {{ font-size: .8rem; text-transform: uppercase; letter-spacing: .08em; color: #8b93a7; margin-bottom: 12px; }}
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

  <div class="cum">{cumulative}</div>

  <div class="rows">{rows}</div>

  {notes}
</div>
</body>
</html>
"""


if __name__ == "__main__":
    build()
