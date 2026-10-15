# HabitTracker: contributor and AI coding guidance

## Purpose

HabitTracker is a personal fitness dashboard for a 3-month challenge. It pulls
habit completion data from a Notion database, computes weekly progress against
targets, and rebuilds `docs/index.html` as a static GitHub Pages dashboard.

## Architecture

```
HabitTracker/
├── scripts/
│   ├── build_dashboard.py    ← main build script; generates docs/index.html
│   └── inspect_notion.py     ← diagnostic: prints raw Notion database schema
├── docs/
│   └── index.html            ← GENERATED — do not edit by hand
├── requirements.txt
└── .gitignore
```

`scripts/build_dashboard.py` is the single entry point. It fetches habit
completion records from Notion, calculates streak and weekly totals for 5
habits, and writes `docs/index.html`. All template logic lives inside that
file; there is no separate Jinja template.

`docs/index.html` is a build artifact. Edit `build_dashboard.py`, then
regenerate — never hand-edit the HTML.

## Credentials

The Notion integration token is read from the environment variable
`NOTION_TOKEN`, or from the file `notion_habit_tracker_token.txt` in the
repository root (gitignored). Neither should ever be committed.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Regenerate the dashboard
python scripts/build_dashboard.py

# Inspect the raw Notion database schema
python scripts/inspect_notion.py

# Serve locally
python -m http.server 8000 --directory docs
```

## Change guidelines

- All habit definitions (names, targets, Notion property keys) live inside
  `build_dashboard.py`. Change them there, not in the generated HTML.
- Do not add external services, databases, or server-side rendering. This is
  a static site regenerated on demand.
- Keep `notion_habit_tracker_token.txt` and any `*.env` files in `.gitignore`.
  Never commit credentials.
- After changing `build_dashboard.py`, regenerate and spot-check `docs/index.html`
  before committing both.
