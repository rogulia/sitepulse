# SitePulse

Lightweight website monitoring tool. Fetches all URLs in your `sitemap.xml`, checks each URL using desktop and mobile User-Agent headers, monitors domain registration and SSL certificate expiry, and sends alerts via Telegram. Supports multiple projects, each with any number of domains.

## Quick Start

```bash
git clone https://github.com/rogulia/sitepulse.git
cd sitepulse
pip install -r requirements.txt
cp .env.example .env            # Telegram token and channel ID
cp config.example.toml config.toml   # your projects and domains
python monitor.py
```

## Features

- **Page monitoring** — checks all URLs in `sitemap.xml` using desktop and mobile User-Agent headers
- **Sitemap index support** — follows child sitemaps; sitemap failures are reported as alerts
- **Compact alerts** — one report per project with a capped list of problem pages
- **Parallel checks** — checks multiple pages concurrently using a thread pool
- **Automatic retries** — retries failed requests once after a 5-second delay
- **Response validation** — checks HTTP status codes, response sizes, and load times
- **Multiple projects** — one config describes any number of projects, each with its own sitemap and domains
- **Domain monitoring** — registration expiry via RDAP with WHOIS fallback, and optional nameserver check
- **SSL monitoring** — certificate expiry and validity (chain, hostname) for every configured host
- **Alert state** — a failing page or endpoint is reported once, repeated after 24 hours if it keeps failing, and a recovery message follows when it is back
- **Telegram alerts** — sends notifications configurable in `config.toml` (`notify_error`, `notify_warning`, `notify_success`)
- **Daily summaries** — generates a 24-hour report and sends it to Telegram
- **Log management** — UTC log timestamps, automatic log rotation with configurable retention period
- **Performance analysis** — built-in tool to analyze logs and identify slowest, largest, and most unstable pages

## Project Structure

```
sitepulse/
├── monitor.py           — main script (page checks, daily summary, domain checks)
├── telegram.py          — Telegram sending (splitting, retries, timeouts)
├── sitemap.py           — sitemap and sitemap index parsing
├── config.py            — loads config.toml and secrets from the environment
├── checks/
│   ├── domain.py        — registration expiry lookup (RDAP, WHOIS)
│   ├── ssl_cert.py      — SSL certificate check
│   └── expiry.py        — runs expiry checks and builds the report
├── tests/
├── config.example.toml  — configuration template
├── utils/
│   ├── analyzer.py      — log analysis and performance reports
│   └── clean_logs.py    — log rotation utility
├── logs/                — log files (created automatically)
├── .env.example         — environment variable template
├── requirements.in      — direct dependencies
├── requirements.txt     — pinned dependencies (generated from requirements.in)
├── action.yml           — composite GitHub Action
└── README.md
```

## Prerequisites

- Python 3.11+
- A Telegram bot token (create one via [@BotFather](https://t.me/BotFather))
- A Telegram channel or group where the bot is an admin

## Configuration

Secrets live in the environment (or `.env`); everything else lives in `config.toml`. The path can be overridden with `SITEPULSE_CONFIG`. The application exits with an error if the config is invalid.

### Environment

| Variable | Description |
|---|---|
| `TELEGRAM_TOKEN` | Telegram bot API token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHANNEL_ID` | Telegram channel or group ID where alerts are sent. Channel IDs typically start with `-100` |
| `SITEPULSE_CONFIG` | Optional path to the config file (default: `config.toml` next to `monitor.py`) |

### `config.toml`

See [config.example.toml](config.example.toml) for a complete template.

`[settings]` (all optional):

| Key | Default | Description |
|---|---|---|
| `min_response_size` | `1000` | Minimum response size in bytes; smaller pages are errors |
| `connect_timeout` / `read_timeout` | `20` / `60` | Timeouts in seconds |
| `slow_response_threshold` | `10` | Responses slower than this (seconds) are warnings |
| `max_workers` | `10` | Parallel threads |
| `notify_success` / `notify_warning` / `notify_error` | `false` / `false` / `true` | Which page check results are sent to Telegram |
| `domain_warn_days` / `domain_critical_days` | `60` / `14` | Registration expiry thresholds |
| `ssl_warn_days` / `ssl_critical_days` | `21` / `7` | Certificate expiry thresholds |
| `log_retention_days` | `10` | Days of log entries kept |

`[[project]]`:

| Key | Description |
|---|---|
| `name` | Unique project name, shown in alerts |
| `url` | Base URL of the site |
| `sitemap` | Optional; default `<url>/sitemap.xml` |
| `health` | Optional list of health endpoint URLs, probed by `--check-health` (any 2xx is healthy, one retry) |

`[[project.domain]]` (repeat for each domain of the project):

| Key | Description |
|---|---|
| `name` | Domain name whose registration is checked |
| `hosts` | Hosts whose SSL certificate is checked; default is the domain itself |
| `nameservers` | Optional; alerts if the registry reports none of them |
| `expiry_fallback` | Optional `YYYY-MM-DD`; used only when RDAP and WHOIS both fail. Needed for TLDs that do not publish expiry dates (for example `.de`) |

## Usage

### Check all pages

Fetches all URLs in the sitemap and checks each one using desktop and mobile User-Agent headers. Sends Telegram alerts based on your notification settings.

```bash
python monitor.py
```

### Daily summary

Cleans old log entries, then sends a summary of the last 24 hours built from the stored run history: runs per check, runs with failures, and what is failing now. A check with no runs in the last 24 hours is reported as such. Ideal for a once-a-day cron job.

```bash
python monitor.py --daily-summary
```

### Alert state

`--check-health` and the page check keep their state in `state/health.json` and `state/pages.json` (override the directory with `SITEPULSE_STATE_DIR`). A new failure is sent immediately; while it persists it is repeated every 24 hours; when the URL passes again a recovery message with the downtime is sent. If a message cannot be delivered, the failure is raised again on the next run. The same files hold the last 48 hours of runs used by the daily summary. Domain and SSL expiry checks keep no state: a persisting problem is reported on every run.

### Health check

Probes the `health` URLs of every project. Only failures are sent (and slow responses when `notify_warning = true`).

```bash
python monitor.py --check-health
```

### Expiry check

Checks domain registration expiry and SSL certificates for every project. Sends one Telegram message per run, only when something needs attention: expiring soon, already expired, invalid certificate, or a lookup that failed. While a problem persists, it is reported on every run.

```bash
python monitor.py --check-expiry
```

### Log analysis

Parses log files and prints a performance report to the terminal: slowest pages, most unstable pages, largest pages, and error/warning counts. Analyzes the last 7 days by default.

```bash
python utils/analyzer.py
```

### Manual log cleanup

Removes log entries older than `log_retention_days`. This also runs automatically as part of `--daily-summary`.

```bash
python utils/clean_logs.py
```

## Automation with Cron

To run monitoring automatically, add cron jobs. Open the crontab editor:

```bash
crontab -e
```

Example schedule:

```cron
# Check pages every 30 minutes
*/30 * * * * cd /path/to/sitepulse && python monitor.py

# Daily summary at 9:00 AM
0 9 * * * cd /path/to/sitepulse && python monitor.py --daily-summary

# Expiry check once a day at 8:00 AM
0 8 * * * cd /path/to/sitepulse && python monitor.py --check-expiry
```

Replace `/path/to/sitepulse` with the actual path to the project directory.

## Run on GitHub Actions

SitePulse ships as a composite action, so you can run it from a separate private repository that holds only your `config.toml` and the schedule. Your domains and URLs stay out of this public repository and out of public workflow logs.

1. Create a private repository and add your `config.toml` (see [config.example.toml](config.example.toml)).
2. In that repository, add the secrets `TELEGRAM_TOKEN` and `TELEGRAM_CHANNEL_ID` (Settings → Secrets and variables → Actions).
3. Copy the workflows from [examples/github-actions](examples/github-actions) to `.github/workflows/`:
   - `health.yml` — health endpoints every 30 minutes;
   - `pages.yml` — full sitemap crawl once a day;
   - `summary.yml` — daily summary;
   - `expiry.yml` — domain and SSL expiry check once a day.
4. Pin the action to a release tag (`rogulia/sitepulse@v1`) or a commit SHA.

Inputs of the action: `mode` (`pages`, `health`, `expiry` or `summary`), `config` (path to the TOML file, default `config.toml`), `telegram-token`, `telegram-channel-id`.

A sitemap crawl requests every URL twice (desktop and mobile), so on large sites run it less often than the health check. Each scheduled run consumes at least one billable minute on private repositories.

GitHub runners are ephemeral, so the `pages` and `health` modes store their state in a `state` branch of the calling repository: one parentless commit, replaced on every run (these workflows need `permissions: contents: write`). The `summary` mode reads that branch. Scheduled runs can start a few minutes late.

## Telegram Alert Examples

**Successful check** (when `notify_success = true`):

```
✅ URL: https://example.com/about
💻 Desktop:
Status: OK (size: 45230 bytes)
Response time: 1.24 sec
📱 Mobile:
Status: OK (size: 44120 bytes)
Response time: 1.31 sec
```

**Error alert:**

```
🚨 URL: https://example.com/broken-page
💻 Desktop:
Error: Response code: 500
📱 Mobile:
Error: Response code: 500
```

**Expiry alert:**

```
📅 Expiry check 02.11.2026 08:00 UTC

🚨 example
- example.com: registration expires in 9 days (11.11.2026)
- www.example.com: SSL certificate expires in 5 days (07.11.2026)
```

**Daily summary:**

```
📊 Daily Summary (23.03.2026)

✅ Health: 48 runs, 0 with failures
⚠️ Pages: 1 runs, 1 with failures
- failing: example https://example.com/broken since 23.03.2026 05:05 UTC
```

**Recovery:**

```
📅 23.03.2026 11:35:02 UTC

✅ example: recovered
- https://example.com/broken (failing for 6h 30m)
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## License

MIT
