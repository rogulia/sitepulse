import argparse
import concurrent.futures
import html
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone as dt_timezone

import requests

from checks.expiry import format_report, run_expiry_checks
from config import (
    LOG_DIR,
    LOG_FILE,
    Config,
    ConfigError,
    Project,
    Settings,
    load_config,
)
from sitemap import fetch_sitemap_urls
from telegram import send_message

logger = logging.getLogger("sitepulse")


def setup_logging() -> None:
    """Set up logging to file and console."""
    os.makedirs(LOG_DIR, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    formatter.converter = time.gmtime

    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


# HTTP headers
DESKTOP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "*",
    "X-Requested-With": "XMLHttpRequest",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}

MOBILE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "*",
    "X-Requested-With": "XMLHttpRequest",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}


def check_single_page(
    url: str, session: requests.Session, settings: Settings
) -> tuple[str, bool, bool, bool]:
    """Check a single page in both desktop and mobile modes."""

    def try_request(headers, device_type):
        start_time = time.time()

        response = session.get(
            url,
            timeout=(settings.connect_timeout, settings.read_timeout),
            headers=headers,
        )
        content_length = len(response.content)
        elapsed_time = time.time() - start_time

        if response.status_code == 200 and content_length >= settings.min_response_size:
            return response, content_length, elapsed_time, None
        else:
            error_msg = None
            if response.status_code != 200:
                error_msg = f"Response code: {response.status_code}"
            else:
                error_msg = f"Response size too small: {content_length} bytes (min. {settings.min_response_size})"
            raise Exception(error_msg)

    messages = []
    has_success = True
    has_warning = False
    has_error = False

    # Check desktop version
    try:
        try:
            response, content_length, elapsed_time, _ = try_request(
                DESKTOP_HEADERS, "Desktop"
            )
        except Exception:
            time.sleep(5)
            response, content_length, elapsed_time, _ = try_request(
                DESKTOP_HEADERS, "Desktop"
            )

        logger.info(
            f"Checked Desktop {url} - status {response.status_code}, size {content_length}, time {elapsed_time:.2f} sec"
        )

        time_info = f"Response time: {elapsed_time:.2f} sec"
        is_slow = elapsed_time > settings.slow_response_threshold
        if is_slow:
            time_info = f"⚠️ {time_info} (threshold {settings.slow_response_threshold} sec exceeded)"
            has_warning = True

        messages.append(
            f"💻 Desktop:\nStatus: OK (size: {content_length} bytes)\n{time_info}"
        )
    except Exception as e:
        logger.error(f"Error checking {url} (Desktop): {e}")
        messages.append(f"💻 Desktop:\nError: {html.escape(str(e))}")
        has_success = False
        has_error = True

    # Check mobile version
    try:
        try:
            response, content_length, elapsed_time, _ = try_request(
                MOBILE_HEADERS, "Mobile"
            )
        except Exception:
            time.sleep(5)
            response, content_length, elapsed_time, _ = try_request(
                MOBILE_HEADERS, "Mobile"
            )

        logger.info(
            f"Checked Mobile {url} - status {response.status_code}, size {content_length}, time {elapsed_time:.2f} sec"
        )

        time_info = f"Response time: {elapsed_time:.2f} sec"
        is_slow = elapsed_time > settings.slow_response_threshold
        if is_slow:
            time_info = f"⚠️ {time_info} (threshold {settings.slow_response_threshold} sec exceeded)"
            has_warning = True

        messages.append(
            f"📱 Mobile:\nStatus: OK (size: {content_length} bytes)\n{time_info}"
        )
    except Exception as e:
        logger.error(f"Error checking {url} (Mobile): {e}")
        messages.append(f"📱 Mobile:\nError: {html.escape(str(e))}")
        has_success = False
        has_error = True

    status_emoji = "🚨" if has_error else ("⚠️" if has_warning else "✅")
    message = f"{status_emoji} URL: {html.escape(url)}\n" + "\n".join(messages)

    return message, has_success and not has_warning, has_warning, has_error


MAX_DETAILED_PAGES = 10


def collect_urls(project: Project, settings: Settings) -> tuple[list[str], list[str]]:
    """Return (urls to check, sitemap problems); falls back to the base URL."""
    result = fetch_sitemap_urls(project.sitemap, settings)
    problems = list(result.errors)
    if not result.urls:
        if not problems:
            problems.append(f"{project.sitemap}: sitemap contains no URLs")
        logger.warning(f"[{project.name}] falling back to base URL {project.url}")
        return [project.url], problems
    return result.urls, problems


def build_project_report(
    name: str,
    total: int,
    results: list[tuple[str, bool, bool, bool]],
    settings: Settings,
) -> str | None:
    """Select results by notification settings; detail at most MAX_DETAILED_PAGES."""
    selected = [
        (message, is_error, is_warning)
        for message, is_success, is_warning, is_error in results
        if (is_success and settings.notify_success)
        or (is_warning and settings.notify_warning)
        or (is_error and settings.notify_error)
    ]
    if not selected:
        return None

    selected.sort(key=lambda r: (not r[1], not r[2]))
    emoji = "🚨" if selected[0][1] else ("⚠️" if selected[0][2] else "✅")
    blocks = [
        f"{emoji} <b>{html.escape(name)}</b>: {len(selected)} of {total} pages reported"
    ]
    blocks.extend(m for m, _, _ in selected[:MAX_DETAILED_PAGES])
    hidden = len(selected) - MAX_DETAILED_PAGES
    if hidden > 0:
        blocks.append(f"… and {hidden} more (see log)")
    return "\n\n".join(blocks)


def check_pages(config: Config) -> None:
    """Check all pages from every project's sitemap."""
    settings = config.settings
    timestamp = datetime.now(dt_timezone.utc).strftime("%d.%m.%Y %H:%M:%S")
    blocks = []
    totals = {}
    results = {project.name: [] for project in config.projects}

    with requests.Session() as session:

        def check_with_session(url):
            return check_single_page(url, session, settings)

        with ThreadPoolExecutor(max_workers=settings.max_workers) as executor:
            future_to_project = {}
            for project in config.projects:
                urls, problems = collect_urls(project, settings)
                totals[project.name] = len(urls)
                if problems and settings.notify_error:
                    lines = "\n".join(f"- {html.escape(p)}" for p in problems)
                    blocks.append(
                        f"🚨 <b>{html.escape(project.name)}</b>: sitemap problems\n{lines}"
                    )
                for url in urls:
                    future_to_project[executor.submit(check_with_session, url)] = (
                        project
                    )

            for future in concurrent.futures.as_completed(future_to_project):
                results[future_to_project[future].name].append(future.result())

    for project in config.projects:
        report = build_project_report(
            project.name, totals[project.name], results[project.name], settings
        )
        if report:
            blocks.append(report)

    if blocks:
        send_message(f"📅 {timestamp} UTC\n\n" + "\n\n".join(blocks))


def send_daily_summary(config: Config) -> None:
    """Send a daily summary report via Telegram."""
    from utils.clean_logs import clean_old_logs

    clean_old_logs(LOG_FILE, config.settings.log_retention_days)

    try:
        logger.info("Starting daily summary generation...")

        with open(LOG_FILE, "r") as f:
            log_lines = f.readlines()

        logger.info(f"Read {len(log_lines)} lines from log file")

        # Filter logs from the last 24 hours
        current_time = datetime.now(dt_timezone.utc)
        logger.info(f"Current time: {current_time}")

        recent_logs = []
        has_errors = False

        for line in log_lines:
            try:
                # Parse timestamp and attach timezone
                timestamp = line.split(" - ")[0]
                # Strip milliseconds before parsing
                timestamp = timestamp.split(",")[0]
                log_time = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                log_time = log_time.replace(tzinfo=dt_timezone.utc)

                time_diff = current_time - log_time
                seconds_diff = time_diff.total_seconds()

                logger.debug(f"Log time: {log_time}, diff: {seconds_diff} seconds")

                if seconds_diff < 24 * 3600:  # 24 hours in seconds
                    recent_logs.append(line)
                    if "ERROR" in line:
                        has_errors = True
            except Exception as e:
                logger.error(f"Error parsing log line '{line.strip()}': {e}")
                continue

        logger.info(
            f"Found {len(recent_logs)} logs in last 24 hours, has_errors: {has_errors}"
        )

        if recent_logs:
            if not has_errors:
                message = (
                    f"📊 Daily Summary ({current_time.strftime('%d.%m.%Y')})\n\n"
                    f"✅ All pages worked correctly during the last 24 hours.\n"
                    f"📝 Total checks: {len(recent_logs)}"
                )
                logger.info("Sending success summary to Telegram")
                send_message(message)
            else:
                message = (
                    f"⚠️ Daily Summary ({current_time.strftime('%d.%m.%Y')})\n\n"
                    f"❌ Found errors in monitoring during last 24 hours.\n"
                    f"📝 Total checks: {len(recent_logs)}"
                )
                logger.info("Sending error summary to Telegram")
                send_message(message)
        else:
            message = (
                f"⚠️ Daily Summary ({current_time.strftime('%d.%m.%Y')})\n\n"
                f"No monitoring data found for the last 24 hours!"
            )
            logger.info("Sending no-data summary to Telegram")
            send_message(message)

    except Exception as e:
        logger.error(f"Error creating daily summary: {e}", exc_info=True)


def check_expiry(config: Config) -> None:
    """Check domain registration and SSL certificate expiry for all projects."""
    now = datetime.now(dt_timezone.utc)
    report = format_report(run_expiry_checks(config), now)
    if report:
        send_message(report)
    else:
        logger.info("Expiry check completed - all OK")


def main() -> None:
    parser = argparse.ArgumentParser(description="SitePulse website monitor")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--daily-summary", action="store_true", help="send the 24h summary"
    )
    mode.add_argument(
        "--check-expiry",
        action="store_true",
        help="check domain registration and SSL certificate expiry",
    )
    args = parser.parse_args()

    setup_logging()
    try:
        config = load_config()
    except ConfigError as e:
        parser.exit(2, f"Configuration error: {e}\n")

    if args.daily_summary:
        send_daily_summary(config)
    elif args.check_expiry:
        check_expiry(config)
    else:
        check_pages(config)


if __name__ == "__main__":
    main()
