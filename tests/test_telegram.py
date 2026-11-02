import logging

import pytest
import requests

import telegram

TOKEN = "123:SECRET"


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.ok = status_code < 400

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setattr(telegram, "telegram_credentials", lambda: (TOKEN, "chat"))
    monkeypatch.setattr(telegram.time, "sleep", lambda _: None)


def test_short_message_is_not_split():
    assert telegram.split_message("header\n\nbody") == ["header\n\nbody"]


def test_long_message_is_split_with_header_and_part_numbers():
    groups = [f"group {i}\n" + "x" * 500 for i in range(20)]
    message = "HEADER\n\n" + "\n\n".join(groups)

    parts = telegram.split_message(message)

    assert len(parts) > 1
    assert all(len(p) <= telegram.MAX_LENGTH + telegram.SUFFIX_RESERVE for p in parts)
    assert all(p.startswith("HEADER\n\n") for p in parts)
    assert parts[-1].endswith(f"Part {len(parts)} of {len(parts)}")
    assert sum(p.count("group ") for p in parts) == 20


def test_oversized_group_is_cut_by_lines():
    message = "HEADER\n\n" + "\n".join("y" * 900 for _ in range(10))
    parts = telegram.split_message(message)
    assert len(parts) > 1
    assert all(len(p) <= telegram.MAX_LENGTH + telegram.SUFFIX_RESERVE for p in parts)


def test_network_error_does_not_log_token(monkeypatch, caplog):
    def boom(url, **_):
        raise requests.ConnectionError(f"failed for {url}")

    monkeypatch.setattr(telegram.requests, "post", boom)
    with caplog.at_level(logging.ERROR):
        assert telegram.send_message("hi") is False

    assert "SECRET" not in caplog.text
    assert "ConnectionError" in caplog.text


def test_rejected_message_logs_status_without_token(monkeypatch, caplog):
    body = {"description": f"Bad Request: can't parse {TOKEN}"}
    monkeypatch.setattr(
        telegram.requests, "post", lambda *a, **k: FakeResponse(400, body)
    )
    with caplog.at_level(logging.ERROR):
        assert telegram.send_message("hi") is False

    assert "400" in caplog.text
    assert "SECRET" not in caplog.text


def test_rate_limit_is_retried_once(monkeypatch):
    responses = iter(
        [FakeResponse(429, {"parameters": {"retry_after": 3}}), FakeResponse(200)]
    )
    calls = []
    monkeypatch.setattr(
        telegram.requests,
        "post",
        lambda *a, **k: calls.append(k["timeout"]) or next(responses),
    )

    assert telegram.send_message("hi") is True
    assert len(calls) == 2
    assert all(calls)
