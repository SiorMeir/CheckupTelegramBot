## CheckupTelegramBot HLD

### What we're trying to achieve
- always-on telegram bot
- daily ping for end-of-day reflection
- weekly ping for end-of-week reflection
- store all responses into parseable data format
- feed llm data for tracking patterns
- deployable on a homelab running k3s (deploy as Deployment)

### slash commands
- /daily - submit daily reivew
- /weekly - submit weekly review
- /statistics - get averages of daily review marks
- /review [month | quarter]- submit aggregated data of X days. has an argument for time period

### Technical design
- python as main programming language
- deploy docker images to a private registry within the k3s cluster
- input to /daily and /weekly is a free text message
    - later: forms
- files will be uploaded to a PVC defined in the deployment of the service
- parsed data will be stored as .md files in the following formats:
    journal/
    ├── daily/
    │   ├── 2026-05-17.md
    │   ├── 2026-05-18.md
    │   └── ...
    ├── weekly/
    │   ├── 2026-week-20.md
    │   └── ...
- scale: single user
