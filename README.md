# CheckupTelegramBot

📝 A small Telegram bot for personal daily check-ins and weekly reviews.

Send markdown, get a clean parsed summary back, and keep every entry stored locally as markdown with YAML frontmatter under `journal/`. It can also ping you on a schedule so the habit does not rely on memory alone.

## ✨ What It Does

- parses daily check-ins and weekly reviews from markdown messages
- stores entries as local files in `journal/daily/` and `journal/weekly/`
- replies with a structured summary after each successful submission
- sends scheduled reminder prompts to a configured Telegram chat

## 💬 UX In Practice

The flow is intentionally lightweight:

- `/start` gives a short greeting
- `/daily` arms your next message as a daily check-in
- `/weekly` arms your next message as a weekly review
- you paste your markdown entry
- the bot parses it, saves it, and replies with a readable summary

⏰ Important: reminder prompts do not auto-arm input. After a reminder, you still need to send `/daily` or `/weekly`.

## 🏠 Self-Hosted Setup

You need:

- a Telegram bot token from `@BotFather`
- optionally, a target chat id for scheduled reminders

Environment variables:

- `TELEGRAM_BOT_TOKEN`: required
- `CHECKUP_CHAT_ID`: optional
- `JOURNAL_ROOT`: optional, defaults to `journal`

### 🐳 Simple Container

Build and run:

```bash
docker build -t checkup-bot .
docker run \
  -e TELEGRAM_BOT_TOKEN=your-token \
  -e CHECKUP_CHAT_ID=your-chat-id \
  -v $(pwd)/journal:/app/journal \
  checkup-bot
```

Mounting `journal/` keeps your entries outside the container so they survive rebuilds and restarts.

### ☸️ Kubernetes / k3s

The repo includes a basic deployment under `deployment/`.

Recommended approach:

1. Build the image and push it to your registry.
2. Create or update the Kubernetes secret with `TELEGRAM_BOT_TOKEN` and optional `CHECKUP_CHAT_ID`.
3. Add persistent storage for `journal/` if you want entries to survive pod replacement.
4. Deploy a single replica only.

Notes:

- keep one replica to avoid duplicate Telegram polling
- DO NOT commit live secrets into `deployment/manifest.yaml`

## 🔧 Local Run

```bash
pip install -r requirements.txt
python app.py
```

Tests:

```bash
python -m pytest tests/
```
