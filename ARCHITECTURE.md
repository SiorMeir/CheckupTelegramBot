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
- /log - count number of entries of each type available and returns them
- /dump - gather all .md files on mounted storage and bundles them as a downloadable file or compressed file

### Technical design
- python as main programming language
- deploy docker images to a private registry within the k3s cluster
- Docker builds must exclude local secrets and generated journal entries from the build context
- runtime containers should run as a non-root user
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
- files will be in .md format for LLM ingestion, with enrichment by frontmatter metadata (applicable to daily entries)
- scale: single user

### Observabillity
- logs should be taken at key points of each command flow
- metrics will be gathered 
- As this suppose to be k8s native, This project should integrate with k8s native observabillity tools.
- The service should expose metric scraping endpoint for Prometheus
- Logs should be stored for a short term in a suitable k8s solution
- example manifests should be detailed in `deployement` folder
    - later: Grafana visuals
### Operational notes
- generated entries under `journal/daily/` and `journal/weekly/` are runtime data and should not be committed
- Docker images should not include local `.env` files, kubeconfigs, or journal output
