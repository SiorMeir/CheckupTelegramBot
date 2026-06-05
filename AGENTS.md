# AGENTS.md - CheckupTelegramBot

Short reference for tooling and humans working on this repo. Product goals and roadmap live in `ARCHITECTURE.md`.

## What this is

A Python Telegram bot that parses markdown daily check-ins and weekly reviews, saves them to a local journal, and sends scheduled reminders to a configured chat.

Implemented capabilities:
- `/start`, `/daily`, `/weekly`
- `/statistics [Nd|Nw|Nm]`
- `/review [Nw]`
- `/log [verbose]`
- `/dump`

Persistence uses markdown files with YAML frontmatter under `journal/`.

1. Telegram bot (`app.py`) - `python-telegram-bot` v22 polling app with:
   - `/start` - short greeting
   - `/daily` - arms the next text message for daily parsing (`AWAITING_DAILY`); clears weekly awaiting state
   - `/weekly` - arms the next text message for weekly parsing (`AWAITING_WEEKLY`); clears daily awaiting state
   - `/statistics [Nd|Nw|Nm]` - computes rolling daily score averages from saved entries
   - `/review [Nw]` - generates an LLM-backed review over the trailing weekly window
   - `/log [verbose]` - counts valid daily and weekly entries, reports the oldest valid entry found, and optionally lists missing coverage by week
   - `/dump` - bundles all journal markdown files into a ZIP and sends it when it fits the Telegram upload limit
   - Text messages - if awaiting daily or weekly, runs `CheckupParser.parse`, validates `DailyCheckIn` vs `WeeklyReview`, saves the raw entry plus frontmatter to the journal, and replies with the rendered summary; otherwise auto-detects daily vs weekly and parses accordingly
   - Scheduled prompts - if `CHECKUP_CHAT_ID` is set, `post_init` registers job-queue reminders: daily at 21:00 and weekly on Saturday at 19:00 (`Asia/Jerusalem`). Prompts do not set awaiting state.
2. Check-in parser (`parser/`) - `CheckupParser` and dataclasses `DailyCheckIn`, `WeeklyReview`
3. Journal storage and reads (`journal/`) - `JournalStore`, `JournalReader`, scan/report helpers, and ZIP export helpers

Runtime journal entries under `journal/daily/` and `journal/weekly/`, plus persisted oversized exports under `journal/exports/`, are ignored by git and excluded from Docker build context so private check-ins are not published accidentally.

## Status vs ARCHITECTURE.md

| Area | Planned (HLD) | Status |
|------|----------------|--------|
| Storage | PVC + `journal/daily/`, `journal/weekly/` `.md` files | Implemented locally; PVC wiring/deployment persistence still not finished |
| `/statistics` | Averages of daily energy/focus/satisfaction | Implemented |
| `/review [month \| quarter]` | Aggregated data for a time period | Implemented as trailing-week windows (`/review Nw`) |
| `/log` | Count stored entries and show coverage gaps | Implemented |
| `/dump` | Bundle journal markdown for download | Implemented with ZIP export and Telegram size fallback |
| LLM / patterns | Feed stored journal data for tracking | Partially enabled through `/review`; broader pattern tracking still open |
| Telegram forms | Structured input instead of free text | Later |
| Reminder UX | Optional: auto-arm awaiting on scheduled ping | Undecided |

## Layout

| Path | Role |
|------|------|
| `ARCHITECTURE.md` | High-level goals, slash commands, journal layout, k3s/PVC design |
| `app.py` | Bot entrypoint, handlers, reminders, `/log`, and `/dump` |
| `journal/store.py` | Atomic daily/weekly markdown persistence with YAML frontmatter |
| `journal/read.py` | Statistics, review collection, and observability scans over saved entries |
| `journal/export.py` | ZIP export helper used by `/dump` |
| `journal/week.py` | Shared Sunday-Saturday week math helpers |
| `parser/parser.py` | `CheckupParser`, models, regex-based extraction |
| `tests/` | Pytest coverage for parsing, storage, scheduling, review, log, and dump flows |
| `requirements.txt` | Pinned dependencies |
| `Dockerfile` | Python 3.12-slim image; runs `python app.py` as a non-root user |
| `deployment/manifest.yaml` | k8s Namespace, Secret, Deployment (single replica, `Recreate` strategy) |

## Running

- Tests:

  ```bash
  python -m pytest tests/
  ```

- Bot:

  ```bash
  set TELEGRAM_BOT_TOKEN=<token from @BotFather>
  set CHECKUP_CHAT_ID=<numeric chat id>
  python app.py
  ```

Environment variables:
- `TELEGRAM_BOT_TOKEN` - Bot API token
- `CHECKUP_CHAT_ID` - Optional chat that receives scheduled prompts
- `JOURNAL_ROOT` - Optional root directory for saved journal files, defaults to `journal`
- `LLM_PROVIDER`, `LLM_MODEL`, `OPENAI_API_KEY`, `LOCAL_BASE_URL`, `REVIEW_MAX_INPUT_TOKENS`, `LLM_TIMEOUT_SECONDS` - review-related config

## Parser contract

- Daily: requires `## Daily Check-In`, score lines like `Energy: 7/10`, and optional bullet sections for today, meaningful, drained, and tomorrow focus
- Weekly: requires a heading containing `Review`, then sections including `Momentum`, `Friction`, `Avoidance`, `Meaningful`, `Fake productivity`, and `Next Week Focus`
- Invalid: unrecognized shapes raise `ValueError("Unknown check-in format")`

## Implementation notes for agents

- Import side effect: `parser/parser.py` still contains demo code at the bottom. Avoid relying on import-time cleanliness there.
- User flow: `/daily` and `/weekly` are mutually exclusive awaiting flags.
- Storage semantics: daily entries are saved by local date and weekly entries by Sunday-Saturday custom week label. A second save for the same date/week overwrites the previous file.
- Observability semantics: `/log` counts only valid parsed entries; `/dump` exports all raw markdown files under the journal daily/weekly roots, including malformed ones.
- Oversized exports: `/dump` persists ZIPs under `journal/exports/` when Telegram upload size is exceeded.
- Reminders: keep one replica in k8s to avoid duplicate Telegram polling.
- Secrets: never commit live `TELEGRAM_BOT_TOKEN` values.
- Style: match existing patterns and keep changes focused unless broader integration is requested.
