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

## 🧾 Example Entries

### Daily check-in

```md
## Daily Check-In

Energy: 7/10
Focus: 6/10
Satisfaction: 8/10

### What did I actually do today?
- Finished the deployment manifest cleanup
- Replied to two pending client messages
- Went for a short walk in the evening

### What felt meaningful?
- Closing the loop on infrastructure work
- Having one calm hour without context switching

### What drained me?
- Too many small interruptions
- Starting the day without a clear priority

### What should tomorrow focus on?
- Ship the README
- Block one uninterrupted work session
```

### Weekly review

```md
## Week 22 Review

### Momentum
- Wrote code consistently on most days
- Kept the bot deployment moving forward

### Friction
- Switched contexts too often
- Let small admin tasks break focus

### Avoidance
- Delayed one uncomfortable technical decision

### Meaningful
- Built something useful for daily reflection
- Had a few work sessions that felt calm and deliberate

### Fake productivity
- Tweaked minor details instead of finishing the important task

### Next Week Focus
- Finish deployment persistence
- Keep daily scope smaller and clearer
```

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
