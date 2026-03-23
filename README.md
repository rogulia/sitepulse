# SitePulse

Lightweight website monitoring tool. Fetches all URLs in your `sitemap.xml`, checks each URL using desktop and mobile User-Agent headers, monitors domain expiration and nameserver settings, and sends alerts via Telegram.

## Quick Start

```bash
git clone https://github.com/rogulia/sitepulse.git
cd sitepulse
pip install -r requirements.txt
cp .env.example .env
# edit .env with your Telegram token and channel ID
python monitor.py
```

## Features

- **Page monitoring** — checks all URLs in `sitemap.xml` using desktop and mobile User-Agent headers
- **Parallel checks** — checks multiple pages concurrently using a thread pool
- **Automatic retries** — retries failed requests once after a 5-second delay
- **Response validation** — checks HTTP status codes, response sizes, and load times
- **Domain monitoring** — monitors domain expiration dates and checks nameserver settings
- **Telegram alerts** — sends notifications configurable via environment variables (`NOTIFY_ERROR`, `NOTIFY_WARNING`, `NOTIFY_SUCCESS`)
- **Daily summaries** — generates a 24-hour report and sends it to Telegram
- **Log management** — automatic log rotation with configurable retention period
- **Performance analysis** — built-in tool to analyze logs and identify slowest, largest, and most unstable pages

## Project Structure

```
sitepulse/
├── monitor.py           — main script (page checks, daily summary, domain checks)
├── config.py            — loads configuration from .env
├── utils/
│   ├── analyzer.py      — log analysis and performance reports
│   └── clean_logs.py    — log rotation utility
├── logs/                — log files (created automatically)
├── .env.example         — environment variable template
├── requirements.txt     — Python dependencies
└── README.md
```

## Prerequisites

- Python 3.10+
- A Telegram bot token (create one via [@BotFather](https://t.me/BotFather))
- A Telegram channel or group where the bot is an admin

## Configuration

All settings are stored in the `.env` file. The application will not start without the required variables.

### Required

| Variable | Description |
|---|---|
| `TELEGRAM_TOKEN` | Telegram bot API token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHANNEL_ID` | Telegram channel or group ID where alerts are sent. Use [@userinfobot](https://t.me/userinfobot) or similar to find it. Channel IDs typically start with `-100` |

### Monitoring Target

| Variable | Default | Description |
|---|---|---|
| `BASE_URL` | `https://example.com` | The base URL of the website to monitor |
| `SITEMAP_PATH` | `/sitemap.xml` | Path to the sitemap file, appended to `BASE_URL` |

### Thresholds

| Variable | Default | Description |
|---|---|---|
| `MIN_RESPONSE_SIZE` | `1000` | Minimum response size in bytes. Pages smaller than this trigger an error |
| `CONNECT_TIMEOUT` | `20` | Connection timeout in seconds |
| `READ_TIMEOUT` | `60` | Read timeout in seconds |
| `SLOW_RESPONSE_THRESHOLD` | `10` | Responses slower than this (in seconds) trigger a warning |
| `MAX_WORKERS` | `10` | Number of parallel threads for page checks |

### Notifications

| Variable | Default | Description |
|---|---|---|
| `NOTIFY_SUCCESS` | `false` | Send a Telegram message for each successful check |
| `NOTIFY_WARNING` | `false` | Send a Telegram message for warnings (slow responses) |
| `NOTIFY_ERROR` | `true` | Send a Telegram message for errors (timeouts, bad status codes, small responses) |

### Domain Monitoring

| Variable | Default | Description |
|---|---|---|
| `DOMAINS_TO_CHECK` | *(empty)* | Comma-separated list of domains. Optionally specify a known expiry date with `:expiry=YYYY-MM-DD` suffix (used as a fallback if WHOIS lookup fails) |
| `OUR_NAMESERVERS` | *(empty)* | Comma-separated list of expected nameservers. Alerts if a domain uses different ones |
| `EXPIRY_WARNING_DAYS` | `90` | Warn this many days before a domain expires |

**`DOMAINS_TO_CHECK` format example:**

```
DOMAINS_TO_CHECK=example.com,example.net:expiry=2025-06-15,example.org
```

### Log Settings

| Variable | Default | Description |
|---|---|---|
| `LOG_RETENTION_DAYS` | `10` | Number of days to keep log entries. Older entries are removed during daily summary |

## Usage

### Check all pages

Fetches all URLs in the sitemap and checks each one using desktop and mobile User-Agent headers. Sends Telegram alerts based on your notification settings.

```bash
python monitor.py
```

### Daily summary

Cleans old log entries, then analyzes the last 24 hours and sends a summary to Telegram. Ideal for a once-a-day cron job.

```bash
python monitor.py --daily-summary
```

### Domain check

Checks domain expiration dates and nameserver settings. Only sends alerts when issues are found.

```bash
python monitor.py --check-domains
```

### Log analysis

Parses log files and prints a performance report to the terminal: slowest pages, most unstable pages, largest pages, and error/warning counts. Analyzes the last 7 days by default.

```bash
python utils/analyzer.py
```

### Manual log cleanup

Removes log entries older than `LOG_RETENTION_DAYS`. This also runs automatically as part of `--daily-summary`.

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

# Domain check once a week on Monday at 10:00 AM
0 10 * * 1 cd /path/to/sitepulse && python monitor.py --check-domains
```

Replace `/path/to/sitepulse` with the actual path to the project directory.

## Telegram Alert Examples

**Successful check** (when `NOTIFY_SUCCESS=true`):

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

**Daily summary (no errors):**

```
📊 Daily Summary (23.03.2026)

✅ All pages worked correctly during the last 24 hours.
📝 Total checks: 384
```

## License

MIT
