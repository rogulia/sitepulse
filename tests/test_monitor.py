import pytest
import requests

import monitor
from config import Project, Settings
from sitemap import SitemapResult

ERR = ("🚨 URL: x", False, False, True)
WARN = ("⚠️ URL: x", False, True, False)
OK = ("✅ URL: x", True, False, False)


def test_report_is_none_when_nothing_to_notify():
    assert monitor.build_project_report("p", 3, [OK, OK, OK], Settings()) is None


def test_report_caps_details_and_orders_errors_first():
    settings = Settings(notify_warning=True)
    results = [WARN] * 3 + [(f"🚨 URL: e{i}", False, False, True) for i in range(15)]

    report = monitor.build_project_report("a&b", 100, results, settings)

    assert report.startswith("🚨 <b>a&amp;b</b>: 18 of 100 pages reported")
    assert report.count("🚨 URL:") == monitor.MAX_DETAILED_PAGES
    assert "⚠️ URL:" not in report
    assert "… and 8 more (see log)" in report


def test_collect_urls_falls_back_and_reports_problem(monkeypatch):
    project = Project("p", "https://a.com", "https://a.com/sitemap.xml")
    monkeypatch.setattr(
        monitor,
        "fetch_sitemap_urls",
        lambda *_: SitemapResult(errors=["https://a.com/sitemap.xml: HTTPError"]),
    )

    urls, problems = monitor.collect_urls(project, Settings())

    assert urls == ["https://a.com"]
    assert problems == ["https://a.com/sitemap.xml: HTTPError"]


def test_collect_urls_empty_sitemap_is_a_problem(monkeypatch):
    project = Project("p", "https://a.com", "https://a.com/sitemap.xml")
    monkeypatch.setattr(monitor, "fetch_sitemap_urls", lambda *_: SitemapResult())

    urls, problems = monitor.collect_urls(project, Settings())

    assert urls == ["https://a.com"]
    assert "no URLs" in problems[0]


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def get(self, url, **_):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class Resp:
    def __init__(self, status):
        self.status_code = status
        self.ok = status < 400


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(monitor.time, "sleep", lambda _: None)


def test_health_ok(no_sleep):
    session = FakeSession([Resp(200)])
    message, is_success, is_warning, is_error = monitor.check_health_url(
        "https://a.com/health", session, Settings()
    )
    assert (is_success, is_warning, is_error) == (True, False, False)
    assert session.calls == 1


def test_health_recovers_on_retry(no_sleep):
    session = FakeSession([Resp(503), Resp(200)])
    _, is_success, _, is_error = monitor.check_health_url(
        "https://a.com/health", session, Settings()
    )
    assert is_success and not is_error
    assert session.calls == 2


def test_health_failure_after_retry_is_error_and_escaped(no_sleep):
    session = FakeSession([requests.ConnectionError("a<b"), Resp(503)])
    message, is_success, _, is_error = monitor.check_health_url(
        "https://a.com/health?x=1&y=2", session, Settings()
    )
    assert is_error and not is_success
    assert "x=1&amp;y=2" in message
    assert "Response code: 503" in message
