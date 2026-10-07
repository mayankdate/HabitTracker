# Habit Tracker

A dashboard for a 3-month fitness challenge (Oct 1 – Dec 31, 2026). It reads a
Notion database where each page is one day, computes per-habit streaks and
completion rates, and publishes a static page to GitHub Pages as a home-tab
motivator. A GitHub Action rebuilds and recommits the page twice every morning.

## Habits tracked

Gym, No Sugar, Good Diet, Water, Jaw Line — each tracked independently with its
own streak and rate. Gym and No Sugar are featured as priority habits. There is
no combined score.

## Project layout

```
HabitTracker/
├── .github/workflows/dashboard.yml   Scheduled build + commit
├── docs/index.html                   The published page (generated)
├── scripts/
│   ├── build_dashboard.py            Fetches Notion, writes docs/index.html
│   └── inspect_notion.py             Diagnostic: prints a database's columns
├── notion_habit_tracker_token.txt    Local token (gitignored, never pushed)
├── requirements.txt
└── README.md
```

## How it works

`scripts/build_dashboard.py` fetches every day from the Notion database
server-side, computes the stats, and writes a fully static `docs/index.html`.
The token is used only during the build — it never appears in the page.

Streaks and dates are computed in IST (a fixed UTC+05:30 offset). The current streak treats
today as pending: an unchecked habit this morning won't reset the streak to
zero, it counts the run ending yesterday until you check in.

## One-time setup

1. **Add the token as a secret.** Repo → Settings → Secrets and variables →
   Actions → New repository secret. Name it exactly `NOTION_TOKEN` and paste the
   same value that's in `notion_habit_tracker_token.txt`.
2. **Enable Pages.** Settings → Pages → Source: Deploy from a branch →
   Branch `main`, folder `/docs`. The site will be at
   `https://<username>.github.io/HabitTracker/`.
3. **First build.** Actions → "Build habit dashboard" → Run workflow. (Or run
   it locally once and commit the generated `docs/index.html`.)

After that the two daily schedules keep it up to date.

## Schedule

GitHub cron runs in UTC. The workflow fires at:

- `57 21 * * *` → 03:27 IST
- `57 2 * * *`  → 08:27 IST

Two runs because GitHub's scheduler can run late or skip one under load — the
second catches a missed first.

## Running locally

```
python scripts/build_dashboard.py
```

Reads the token from the `NOTION_TOKEN` environment variable, or from
`notion_habit_tracker_token.txt` in the project root. Writes `docs/index.html`,
which you can open in a browser.

To check the database's columns (e.g. after changing the schema):

```
python scripts/inspect_notion.py
```

## Notes

- **The repo is public, so the habit data on the page is public.**
- The Notion data source ID is set as a constant in `build_dashboard.py`. If you
  rebuild the database, update it there.
- The scripts need no third-party packages — only the Python standard library
  (Python 3).
