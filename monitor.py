import argparse
import concurrent.futures
import html
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as dt_timezone

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
from state import (
    append_run,
    format_duration,
    load_state,
    reconcile,
    save_state,
)
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


KEY_SEPARATOR = "\t"


def process_outcomes(
    state_name: str,
    config: Config,
    outcomes: dict[str, list[tuple[str, tuple[str, bool, bool, bool]]]],
    totals: dict[str, int],
    blocks: list[str],
) -> None:
    """Report new failures, reminders and recoveries; persist the failure state.

    `outcomes` maps a project name to (url, check result) pairs. A failure already
    reported is silent until the reminder interval passes or it recovers.
    """
    settings = config.settings
    now = datetime.now(dt_timezone.utc)
    data = load_state(state_name)

    probed = {}
    for project_name, items in outcomes.items():
        for url, result in items:
            probed[f"{project_name}{KEY_SEPARATOR}{url}"] = result
    current = {key: result[0] for key, result in probed.items() if result[3]}
    transitions = reconcile(data["failing"], current, set(probed), now)

    for project in config.projects:
        results = []
        for key, result in probed.items():
            if not key.startswith(project.name + KEY_SEPARATOR):
                continue
            if result[3]:
                kind = transitions.alerts.get(key)
                if kind is None:
                    continue
                if kind == "reminder":
                    since = datetime.fromisoformat(transitions.failing[key]["since"])
                    prefix = f"🔁 Still failing for {format_duration(now - since)}\n"
                    result = (prefix + result[0], *result[1:])
            results.append(result)
        report = build_project_report(
            project.name, totals[project.name], results, settings
        )
        if report:
            blocks.append(report)

        if settings.notify_error:
            recovered = [
                f"- {html.escape(key.split(KEY_SEPARATOR, 1)[1])} "
                f"(failing for {format_duration(downtime)})"
                for key, downtime in transitions.recovered.items()
                if key.startswith(project.name + KEY_SEPARATOR)
            ]
            hidden = len(recovered) - MAX_DETAILED_PAGES
            if hidden > 0:
                recovered = recovered[:MAX_DETAILED_PAGES] + [f"… and {hidden} more"]
            if recovered:
                blocks.append(
                    f"✅ <b>{html.escape(project.name)}</b>: recovered\n"
                    + "\n".join(recovered)
                )

    timestamp = now.strftime("%d.%m.%Y %H:%M:%S")
    delivered = True
    if blocks:
        delivered = send_message(f"📅 {timestamp} UTC\n\n" + "\n\n".join(blocks))

    # An undelivered report keeps the old failure state, so it is raised again next run.
    if delivered:
        data["failing"] = transitions.failing
    append_run(data, now, checked=len(probed), failed=len(current))
    save_state(state_name, data)


def check_pages(config: Config) -> None:
    """Check all pages from every project's sitemap."""
    settings = config.settings
    blocks = []
    totals = {}
    outcomes = {project.name: [] for project in config.projects}

    with requests.Session() as session:

        def check_with_session(url):
            return check_single_page(url, session, settings)

        with ThreadPoolExecutor(max_workers=settings.max_workers) as executor:
            future_to_probe = {}
            for project in config.projects:
                urls, problems = collect_urls(project, settings)
                totals[project.name] = len(urls)
                if problems and settings.notify_error:
                    lines = "\n".join(f"- {html.escape(p)}" for p in problems)
                    blocks.append(
                        f"🚨 <b>{html.escape(project.name)}</b>: sitemap problems\n{lines}"
                    )
                for url in urls:
                    future = executor.submit(check_with_session, url)
                    future_to_probe[future] = (project, url)

            for future in concurrent.futures.as_completed(future_to_probe):
                project, url = future_to_probe[future]
                outcomes[project.name].append((url, future.result()))

    process_outcomes("pages", config, outcomes, totals, blocks)


HEALTH_USER_AGENT = "SitePulse-health/1.0"
HEALTH_RETRY_DELAY = 5


def check_health_url(
    url: str, session: requests.Session, settings: Settings
) -> tuple[str, bool, bool, bool]:
    """Probe a health endpoint: any 2xx is healthy, one retry on failure."""
    error = None
    for attempt in (1, 2):
        start = time.time()
        try:
            response = session.get(
                url,
                timeout=(settings.connect_timeout, settings.read_timeout),
                headers={"User-Agent": HEALTH_USER_AGENT},
            )
            elapsed = time.time() - start
            if response.ok:
                logger.info(
                    f"Health {url} - status {response.status_code}, time {elapsed:.2f} sec"
                )
                is_slow = elapsed > settings.slow_response_threshold
                emoji = "⚠️" if is_slow else "✅"
                detail = f"Response time: {elapsed:.2f} sec" + (
                    f" (threshold {settings.slow_response_threshold} sec exceeded)"
                    if is_slow
                    else ""
                )
                message = f"{emoji} Health: {html.escape(url)}\n{detail}"
                return message, not is_slow, is_slow, False
            error = f"Response code: {response.status_code}"
        except requests.RequestException as e:
            error = f"{type(e).__name__}: {e}"
        if attempt == 1:
            time.sleep(HEALTH_RETRY_DELAY)

    logger.error(f"Health check failed {url}: {error}")
    message = f"🚨 Health: {html.escape(url)}\nError: {html.escape(error)}"
    return message, False, False, True


def check_health(config: Config) -> None:
    """Probe the health endpoints of every project."""
    settings = config.settings
    outcomes = {project.name: [] for project in config.projects}
    totals = {project.name: len(project.health) for project in config.projects}

    with requests.Session() as session:
        with ThreadPoolExecutor(max_workers=settings.max_workers) as executor:
            futures = {
                executor.submit(check_health_url, url, session, settings): (
                    project,
                    url,
                )
                for project in config.projects
                for url in project.health
            }
            for future in concurrent.futures.as_completed(futures):
                project, url = futures[future]
                outcomes[project.name].append((url, future.result()))

    process_outcomes("health", config, outcomes, totals, [])


SUMMARY_MODES = (("Health", "health"), ("Pages", "pages"))
MAX_SUMMARY_FAILURES = 10


def build_summary(now: datetime) -> str:
    """Summarize the last 24 hours from the stored run history."""
    lines = []
    for label, name in SUMMARY_MODES:
        data = load_state(name)
        if not data["runs"]:
            continue
        cutoff = now - timedelta(hours=24)
        runs = [r for r in data["runs"] if datetime.fromisoformat(r["ts"]) >= cutoff]
        if not runs:
            lines.append(f"⚠️ {label}: no runs in the last 24 hours")
            continue
        failed_runs = sum(1 for r in runs if r["failed"])
        healthy = not failed_runs and not data["failing"]
        lines.append(
            f"{'✅' if healthy else '⚠️'} {label}: {len(runs)} runs, "
            f"{failed_runs} with failures"
        )
        for key, entry in list(data["failing"].items())[:MAX_SUMMARY_FAILURES]:
            project, _, url = key.partition(KEY_SEPARATOR)
            since = datetime.fromisoformat(entry["since"]).strftime("%d.%m.%Y %H:%M")
            lines.append(
                f"- failing: {html.escape(project)} {html.escape(url)} since {since} UTC"
            )
        hidden = len(data["failing"]) - MAX_SUMMARY_FAILURES
        if hidden > 0:
            lines.append(f"… and {hidden} more failing")

    header = f"📊 Daily Summary ({now.strftime('%d.%m.%Y')})"
    if not lines:
        return header + "\n\n⚠️ No monitoring data found"
    return header + "\n\n" + "\n".join(lines)


def send_daily_summary(config: Config) -> None:
    """Send the daily summary built from stored run history."""
    from utils.clean_logs import clean_old_logs

    clean_old_logs(LOG_FILE, config.settings.log_retention_days)
    send_message(build_summary(datetime.now(dt_timezone.utc)))


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
        "--check-health",
        action="store_true",
        help="probe the health endpoints listed in the config",
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
    elif args.check_health:
        check_health(config)
    elif args.check_expiry:
        check_expiry(config)
    else:
        check_pages(config)


if __name__ == "__main__":
    main()
