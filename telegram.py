import logging
import time

import requests

from config import telegram_credentials

logger = logging.getLogger(__name__)

MAX_LENGTH = 4000  # safety margin from the 4096 limit
SUFFIX_RESERVE = 20  # room for "\nPart 99 of 99"
REQUEST_TIMEOUT = (10, 30)
MAX_RETRY_AFTER = 30


def _chunk_group(group: str, budget: int) -> list[str]:
    if len(group) <= budget:
        return [group]
    chunks, current = [], ""
    for line in group.split("\n"):
        if len(line) > budget:
            line = line[: budget - 1] + "…"
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > budget:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def split_message(message: str, limit: int = MAX_LENGTH) -> list[str]:
    """Split on blank lines; the first paragraph is a header repeated in every part."""
    if len(message) <= limit:
        return [message]

    header, *groups = message.split("\n\n")
    budget = limit - len(header) - 2 - SUFFIX_RESERVE
    parts, current, size = [], [], 0
    for group in groups:
        for piece in _chunk_group(group, budget):
            added = len(piece) + (2 if current else 0)
            if current and size + added > budget:
                parts.append(current)
                current, size, added = [], 0, len(piece)
            current.append(piece)
            size += added
    if current:
        parts.append(current)

    total = len(parts)
    return [
        f"{header}\n\n" + "\n\n".join(part) + f"\nPart {i} of {total}"
        for i, part in enumerate(parts, 1)
    ]


def _post(token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    for attempt in (1, 2):
        try:
            response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            # The exception text contains the request URL, which includes the token.
            logger.error(f"Telegram request failed: {type(e).__name__}")
            return False

        if response.ok:
            return True

        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code == 429 and attempt == 1:
            retry_after = body.get("parameters", {}).get("retry_after", 5)
            time.sleep(min(retry_after, MAX_RETRY_AFTER))
            continue

        description = str(body.get("description", "")).replace(token, "***")
        logger.error(f"Telegram rejected message: {response.status_code} {description}")
        return False
    return False


def send_message(message: str) -> bool:
    """Send a message to the configured chat; returns True if every part was delivered."""
    token, chat_id = telegram_credentials()
    parts = split_message(message)
    delivered = True
    for i, part in enumerate(parts):
        if i:
            time.sleep(1)
        delivered = _post(token, chat_id, part) and delivered
    return delivered
