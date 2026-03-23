import requests
import logging
from typing import List
from datetime import datetime
from pytz import timezone
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
import time
import whois
import sys
import xml.etree.ElementTree as ET

from config import (
    TELEGRAM_TOKEN,
    TELEGRAM_CHANNEL_ID,
    BASE_URL,
    SITEMAP_URL,
    MIN_RESPONSE_SIZE,
    CONNECT_TIMEOUT,
    READ_TIMEOUT,
    SLOW_RESPONSE_THRESHOLD,
    MAX_WORKERS,
    NOTIFY_SUCCESS,
    NOTIFY_WARNING,
    NOTIFY_ERROR,
    EXPIRY_WARNING_DAYS,
    LOG_FILE,
    DOMAINS_TO_CHECK,
    OUR_NAMESERVERS,
)


# Logging setup
def setup_logging():
    """Set up logging to file and console."""
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logger = logging.getLogger(__name__)
    logger.debug("Logging configured")
    return logger


logger = setup_logging()
logger.debug("Script started")

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

logger.debug("HTTP headers configured")
logger.debug(f"Using sitemap: {SITEMAP_URL}")


def get_urls_from_sitemap(sitemap_url: str) -> List[str]:
    """Fetch and parse URLs from a sitemap.xml, auto-detecting XML namespace."""
    logger.debug(f"Fetching URLs from sitemap: {sitemap_url}")
    try:
        logger.debug(f"Sending request to {sitemap_url}")
        response = requests.get(sitemap_url, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
        response.raise_for_status()
        logger.debug(
            f"Response received: status {response.status_code}, size {len(response.content)} bytes"
        )

        # Parse XML
        logger.debug("Parsing XML")
        root = ET.fromstring(response.content)

        # Detect namespace from the document
        logger.debug("Detecting namespace")
        root_attrs = root.attrib
        logger.debug(f"Root element attributes: {root_attrs}")
        logger.debug(f"Root element tag: {root.tag}")

        # Extract namespace from the root element tag
        namespace_uri = None
        if "}" in root.tag:
            namespace_uri = root.tag.split("}")[0][1:]
            logger.debug(f"Found namespace in root tag: {namespace_uri}")
        else:
            # Check default xmlns attribute
            if "xmlns" in root_attrs:
                namespace_uri = root_attrs["xmlns"]
                logger.debug(f"Found default namespace: {namespace_uri}")

            # Check prefixed xmlns: attributes
            if not namespace_uri:
                for attr_name, attr_value in root_attrs.items():
                    if attr_name.startswith("xmlns:"):
                        namespace_uri = attr_value
                        logger.debug(
                            f"Found namespace with prefix {attr_name}: {namespace_uri}"
                        )
                        break

            # Fall back to default sitemap namespace
            if not namespace_uri:
                namespace_uri = "http://www.sitemaps.org/schemas/sitemap/0.9"
                logger.warning(
                    f"Namespace not found in sitemap, using default: {namespace_uri}"
                )

        namespace = {"ns": namespace_uri}

        # Extract URLs
        logger.debug("Extracting URLs")
        urls = []
        url_elements = root.findall(".//ns:url", namespace)
        logger.debug(f"Found {len(url_elements)} url elements")

        for url_elem in url_elements:
            loc_elem = url_elem.find("ns:loc", namespace)
            if loc_elem is not None:
                url = loc_elem.text
                urls.append(url)
                logger.debug(f"Added URL: {url}")

        logger.debug(f"Found {len(urls)} URLs in sitemap")
        logger.debug(f"First 5 URLs: {urls[:5]}")
        return urls

    except Exception as e:
        logger.error(f"Error fetching sitemap: {e}", exc_info=True)
        logger.warning(f"Falling back to base URL: {BASE_URL}")
        return [BASE_URL]


# Fetch URLs from sitemap
logger.debug("Starting URL fetch from sitemap")
URLS_TO_CHECK = get_urls_from_sitemap(SITEMAP_URL)
logger.debug(f"Fetched {len(URLS_TO_CHECK)} URLs to check")


def send_telegram_message(message: str) -> None:
    """Send a message to the Telegram channel, splitting if too long."""
    max_length = 4000  # Safety margin from the 4096 limit
    telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    # If message fits in one chunk, send as-is
    if len(message) <= max_length:
        payload = {
            "chat_id": TELEGRAM_CHANNEL_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            response = requests.post(telegram_api_url, json=payload)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Error sending to Telegram: {e}")
        return

    # Split into parts by message groups
    parts = []
    current_part = []
    current_length = 0

    # Extract the first line (timestamp header)
    first_line = message.split("\n\n")[0]

    # Split the rest into groups (one URL report each)
    message_groups = message.split("\n\n")[1:]

    for group in message_groups:
        group_text = group + "\n\n"
        group_length = len(group_text)

        # If adding this group would exceed the limit
        if current_length + group_length > max_length:
            if current_part:
                parts.append(first_line + "\n\n" + "".join(current_part))
            current_part = [group_text]
            current_length = len(first_line) + 2 + group_length
        else:
            current_part.append(group_text)
            current_length += group_length

    # Append the last part
    if current_part:
        parts.append(first_line + "\n\n" + "".join(current_part))

    # Send each part
    for i, part in enumerate(parts, 1):
        if part.strip():
            payload = {
                "chat_id": TELEGRAM_CHANNEL_ID,
                "text": f"{part.strip()}\nPart {i} of {len(parts)}",
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            try:
                response = requests.post(telegram_api_url, json=payload)
                response.raise_for_status()
                time.sleep(1)  # Small delay between sends
            except Exception as e:
                logger.error(f"Error sending part {i} to Telegram: {e}")


def check_single_page(
    url: str, session: requests.Session
) -> tuple[str, bool, bool, bool]:
    """Check a single page in both desktop and mobile modes."""

    def try_request(headers, device_type):
        start_time = time.time()

        response = session.get(
            url, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), headers=headers
        )
        content_length = len(response.content)
        elapsed_time = time.time() - start_time

        if response.status_code == 200 and content_length >= MIN_RESPONSE_SIZE:
            return response, content_length, elapsed_time, None
        else:
            error_msg = None
            if response.status_code != 200:
                error_msg = f"Response code: {response.status_code}"
            else:
                error_msg = f"Response size too small: {content_length} bytes (min. {MIN_RESPONSE_SIZE})"
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
        is_slow = elapsed_time > SLOW_RESPONSE_THRESHOLD
        if is_slow:
            time_info = (
                f"⚠️ {time_info} (threshold {SLOW_RESPONSE_THRESHOLD} sec exceeded)"
            )
            has_warning = True

        messages.append(
            f"💻 Desktop:\nStatus: OK (size: {content_length} bytes)\n{time_info}"
        )
    except Exception as e:
        logger.error(f"Error checking {url} (Desktop): {e}")
        messages.append(f"💻 Desktop:\nError: {str(e)}")
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
        is_slow = elapsed_time > SLOW_RESPONSE_THRESHOLD
        if is_slow:
            time_info = (
                f"⚠️ {time_info} (threshold {SLOW_RESPONSE_THRESHOLD} sec exceeded)"
            )
            has_warning = True

        messages.append(
            f"📱 Mobile:\nStatus: OK (size: {content_length} bytes)\n{time_info}"
        )
    except Exception as e:
        logger.error(f"Error checking {url} (Mobile): {e}")
        messages.append(f"📱 Mobile:\nError: {str(e)}")
        has_success = False
        has_error = True

    status_emoji = "🚨" if has_error else ("⚠️" if has_warning else "✅")
    message = f"{status_emoji} URL: {url}\n" + "\n".join(messages)

    return message, has_success and not has_warning, has_warning, has_error


def check_pages() -> None:
    """Check all pages from the sitemap."""
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    messages_to_send = []

    with requests.Session() as session:

        def check_with_session(url):
            return check_single_page(url, session)

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_url = {
                executor.submit(check_with_session, url): url for url in URLS_TO_CHECK
            }

            for future in concurrent.futures.as_completed(future_to_url):
                message, is_success, is_warning, is_error = future.result()

                # Add message according to notification settings
                if (
                    (is_success and NOTIFY_SUCCESS)
                    or (is_warning and NOTIFY_WARNING)
                    or (is_error and NOTIFY_ERROR)
                ):
                    messages_to_send.append(message)

    # Send if there are messages to deliver
    if messages_to_send:
        message = f"📅 {timestamp}\n\n" + "\n\n".join(messages_to_send)
        send_telegram_message(message)


def send_daily_summary() -> None:
    """Send a daily summary report via Telegram."""
    from utils.clean_logs import clean_old_logs

    clean_old_logs(LOG_FILE)

    try:
        logger.info("Starting daily summary generation...")

        with open(LOG_FILE, "r") as f:
            log_lines = f.readlines()

        logger.info(f"Read {len(log_lines)} lines from log file")

        # Filter logs from the last 24 hours
        current_time = datetime.now(timezone("Europe/Helsinki"))
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
                log_time = timezone("Europe/Helsinki").localize(log_time)

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
                send_telegram_message(message)
            else:
                message = (
                    f"⚠️ Daily Summary ({current_time.strftime('%d.%m.%Y')})\n\n"
                    f"❌ Found errors in monitoring during last 24 hours.\n"
                    f"📝 Total checks: {len(recent_logs)}"
                )
                logger.info("Sending error summary to Telegram")
                send_telegram_message(message)
        else:
            message = (
                f"⚠️ Daily Summary ({current_time.strftime('%d.%m.%Y')})\n\n"
                f"No monitoring data found for the last 24 hours!"
            )
            logger.info("Sending no-data summary to Telegram")
            send_telegram_message(message)

    except Exception as e:
        logger.error(f"Error creating daily summary: {e}", exc_info=True)


def check_domain(domain: str) -> tuple[str, bool]:
    """Check domain registration expiry and nameservers."""
    try:
        w = whois.whois(domain)

        # Check expiration date
        if isinstance(w.expiration_date, list):
            expiry_date = min(w.expiration_date)  # use the earliest date if multiple
        else:
            expiry_date = w.expiration_date

        if expiry_date is None:
            message = (
                f"⚠️ Domain: {domain}\nCould not get expiration date, check manually"
            )
            return message, True

        days_until_expiry = (expiry_date - datetime.now()).days

        # Check nameservers
        domain_ns = [ns.lower() for ns in w.name_servers]
        our_ns = [ns.lower() for ns in OUR_NAMESERVERS]
        using_our_ns = any(ns in domain_ns for ns in our_ns)

        messages = []
        has_warning = False

        if days_until_expiry <= EXPIRY_WARNING_DAYS:
            messages.append(
                f"⚠️ Domain will expire in {days_until_expiry} days ({expiry_date.strftime('%Y-%m-%d')})"
            )
            has_warning = True

        if not using_our_ns:
            messages.append(
                "⚠️ Domain is using external nameservers:\n"
                + "\n".join(f"- {ns}" for ns in domain_ns)
            )
            has_warning = True

        if not has_warning:
            message = (
                f"✅ Domain: {domain}\n"
                f"Expiry: {expiry_date.strftime('%Y-%m-%d')} ({days_until_expiry} days)\n"
                f"Nameservers OK"
            )
            return message, False
        else:
            message = f"🚨 Domain: {domain}\n" + "\n".join(messages)
            return message, True

    except Exception as e:
        message = f"🚨 Error checking domain {domain}: {str(e)}"
        return message, True


def check_domains() -> None:
    """Check all configured domains for expiry and nameserver issues."""
    timestamp = datetime.now(timezone("Europe/Helsinki")).strftime("%d.%m.%Y %H:%M:%S")
    warning_messages = []  # Only collect messages with warnings

    for domain in DOMAINS_TO_CHECK:
        message, has_warning = check_domain(domain)
        if has_warning:  # Only include domains with issues
            warning_messages.append(message)

    if warning_messages:  # Only send report if there are issues
        full_message = f"📅 Domain Check {timestamp}\n\n" + "\n\n".join(
            warning_messages
        )
        send_telegram_message(full_message)
    else:
        logger.info("Domain check completed - all OK")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "--daily-summary":
            send_daily_summary()
        elif sys.argv[1] == "--check-domains":
            check_domains()
        else:
            check_pages()
    else:
        check_pages()
