# AGENTS.md — CheckupTelegramBot

Short reference for tooling and humans working on this repo. Product goals and roadmap live in **`ARCHITECTURE.md`**.

## What this is

A Python Telegram bot that parses markdown **daily check-ins** and **weekly reviews**, saves them to a local journal, and sends scheduled reminders to a configured chat. **Persistence is implemented** via markdown files with YAML frontmatter under `journal/`; `/statistics` and `/review` are still not implemented (see [Not implemented](#not-implemented-vs-architecturemd)).

1. **Telegram bot** (`app.py`) — [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) v22 polling app with:
   - `/start` — short greeting
   - `/daily` — arms the next text message for daily parsing (`AWAITING_DAILY`); clears weekly awaiting state
   - `/weekly` — arms the next text message for weekly parsing (`AWAITING_WEEKLY`); clears daily awaiting state
   - **Text messages** — if awaiting daily or weekly, runs `CheckupParser.parse`, validates `DailyCheckIn` vs `WeeklyReview`, saves the raw entry plus frontmatter to the journal, and replies with `format_parsed_daily` or `format_parsed_weekly`; otherwise replies that nothing is armed
   - **Scheduled prompts** — if `CHECKUP_CHAT_ID` is set, `post_init` registers job-queue reminders: daily at 21:00 and weekly on Saturday at 19:00 (`Asia/Jerusalem`). Prompts are plain messages; they **do not** set awaiting state (user must `/daily` or `/weekly` to submit)
2. **Check-in parser** (`parser/`) — `CheckupParser` and dataclasses `DailyCheckIn`, `WeeklyReview`; covered by unit tests and imported by the bot.
3. **Journal storage** (`journal/`) — `JournalStore` writes `journal/daily/YYYY-MM-DD.md` and `journal/weekly/YYYY-week-WW.md` atomically with simple YAML frontmatter. Root path defaults to `journal/` and can be overridden with `JOURNAL_ROOT`.

## Not implemented (vs ARCHITECTURE.md)

| Area | Planned (HLD) | Status |
|------|----------------|--------|
| Storage | PVC + `journal/daily/`, `journal/weekly/` `.md` files | Implemented locally; PVC wiring/deployment persistence still not finished |
| `/statistics` | Averages of daily energy/focus/satisfaction | Not started |
| `/review [month \| quarter]` | Aggregated data for a time period | Not started |
| LLM / patterns | Feed stored journal data for tracking | Blocked on statistics/review layer |
| Telegram forms | Structured input instead of free text | Later |
| Reminder UX | Optional: auto-arm awaiting on scheduled ping | Undecided |

## Layout

| Path | Role |
|------|------|
| `ARCHITECTURE.md` | High-level goals, slash commands, journal layout, k3s/PVC design |
| `app.py` | Bot entrypoint, handlers, formatters, reminders (`post_init`), `run_polling()` |
| `journal/store.py` | `JournalStore` for atomic daily/weekly markdown persistence with YAML frontmatter |
| `journal/__init__.py` | Re-exports `JournalStore` |
| `parser/parser.py` | `CheckupParser`, models, regex-based extraction |
| `parser/__init__.py` | Re-exports `CheckupParser`, `DailyCheckIn`, `WeeklyReview` |
| `tests/parser_test.py` | Pytest coverage for daily + weekly parsing and invalid input |
| `tests/app_test.py` | Pytest for reminder scheduling (`post_init`, `scheduled_checkup_prompt`) |
| `tests/journal_store_test.py` | Pytest for journal file layout, frontmatter, and atomic writes |
| `tests/app_storage_test.py` | Pytest that daily/weekly handlers save to journal and degrade cleanly on write failure |
| `requirements.txt` | Pinned deps (`python-telegram-bot`, `python-dotenv`, `pytest`, etc.) |
| `Dockerfile` | Python 3.12-slim image; installs deps and runs `python app.py` |
| `deployment/manifest.yaml` | k8s Namespace, Secret, Deployment (single replica, `Recreate` strategy) |
| `deployment/apply.ps1` | Substitutes env into manifest placeholders, then `kubectl apply` |
| `deployment/registry.yaml` | In-cluster registry service (homelab) |
| `deployment/k3s-registries.yaml.example` | Node config snippet for HTTP registry on k3s |
| `.gitignore` | Ignores `venv/`, `.env*`, bytecode |

## Running

- **Tests** (from repo root, with venv activated if you use one):

  ```bash
  python -m pytest tests/
  ```

- **Bot** — set env vars (or use a `.env` file; `load_dotenv()` runs at startup):

  ```bash
  set TELEGRAM_BOT_TOKEN=<token from @BotFather>
  set CHECKUP_CHAT_ID=<numeric chat id>   # optional; omit to disable reminders
  python app.py
  ```

  | Variable | Purpose |
  |----------|---------|
  | `TELEGRAM_BOT_TOKEN` | Bot API token (defaults to `YOUR_BOT_TOKEN_HERE` if unset) |
  | `CHECKUP_CHAT_ID` | Chat that receives scheduled daily/weekly prompts |
  | `JOURNAL_ROOT` | Optional root directory for saved journal files (defaults to `journal`) |

  `.gitignore` excludes `.env` files; do not commit tokens.

- **Docker**:

  ```bash
  docker build -t checkup-bot .
  docker run --env TELEGRAM_BOT_TOKEN=... --env CHECKUP_CHAT_ID=... checkup-bot
  ```

- **Kubernetes** — do not `kubectl apply` `manifest.yaml` raw if it still contains `${TELEGRAM_BOT_TOKEN}` placeholders or live secrets. Use `deployment/apply.ps1` with env set, or edit the Secret locally without committing. Deployment injects `TELEGRAM_BOT_TOKEN` and optional `CHECKUP_CHAT_ID` from the Secret (matches `app.py`). Keep **one replica** (`Recreate` strategy) to avoid duplicate pollers.

## Parser contract

- **Daily**: Markdown must contain `## Daily Check-In`. Expects lines like `Energy: 7/10` (same for Focus, Satisfaction). Bullet sections use markdown list lines under headings such as `What did I actually do today?`, `What felt meaningful?`, `What drained me?`, `What should tomorrow focus on?`. Missing scores raise `ValueError`; missing bullet sections become empty lists.

- **Weekly**: `CheckupParser.parse` treats input as weekly if it does **not** match daily but contains the substring `Review` — a loose heuristic (`"## Week 2 Review"` matches). Sections include `Momentum`, `Friction`, `Avoidance`, `Meaningful`, `Fake productivity`, `Next Week Focus` (bullets under each).

- **Invalid**: Unrecognized shapes raise `ValueError("Unknown check-in format")`.

## Implementation notes for agents

- **Import side effect**: Importing `parser.parser` runs the demo at the bottom (`parse` + `print`). Prefer `if __name__ == "__main__":` if you need a clean import-only module.
- **User flow**: `/daily` and `/weekly` are mutually exclusive awaiting flags. Handlers use `isinstance(parsed, DailyCheckIn)` or `WeeklyReview` after parse — do not treat a successful parse as both types.
- **Storage semantics**: Daily entries are saved by local date and weekly entries by ISO week. A second save for the same date/week overwrites the previous file.
- **Reminders**: Use a single replica in k8s — multiple pollers would duplicate Telegram updates.
- **Secrets**: Never commit real `TELEGRAM_BOT_TOKEN` values in `deployment/manifest.yaml`; rotate any token that was committed.
- **Style**: Match existing patterns; keep changes minimal unless the task asks for broader integration (e.g. journal storage should follow `ARCHITECTURE.md` paths).
