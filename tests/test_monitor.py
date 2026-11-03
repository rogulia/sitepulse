import pytest
import requests

import monitor
from config import Config, Project, Settings
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


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SITEPULSE_STATE_DIR", str(tmp_path))
    return tmp_path


def run_outcomes(monkeypatch, outcomes, deliver=True):
    sent = []
    monkeypatch.setattr(
        monitor, "send_message", lambda text: sent.append(text) or deliver
    )
    project = Project("p", "https://a.com", "https://a.com/sitemap.xml")
    config = Config(Settings(), (project,))
    totals = {"p": len(outcomes)}
    monitor.process_outcomes("health", config, {"p": outcomes}, totals, [])
    return sent


DOWN = ("🚨 Health: x", False, False, True)
UP = ("✅ Health: x", True, False, False)


def test_failure_alerts_once_then_recovery(state_dir, monkeypatch):
    first = run_outcomes(monkeypatch, [("https://a.com/h", DOWN)])
    second = run_outcomes(monkeypatch, [("https://a.com/h", DOWN)])
    third = run_outcomes(monkeypatch, [("https://a.com/h", UP)])
    fourth = run_outcomes(monkeypatch, [("https://a.com/h", UP)])

    assert len(first) == 1 and "🚨 Health" in first[0]
    assert second == []
    assert len(third) == 1 and "recovered" in third[0] and "https://a.com/h" in third[0]
    assert fourth == []


def test_undelivered_alert_is_raised_again(state_dir, monkeypatch):
    run_outcomes(monkeypatch, [("https://a.com/h", DOWN)], deliver=False)
    retry = run_outcomes(monkeypatch, [("https://a.com/h", DOWN)])
    assert len(retry) == 1 and "🚨 Health" in retry[0]


def test_runs_are_recorded_and_summarized(state_dir, monkeypatch):
    run_outcomes(monkeypatch, [("https://a.com/h", UP)])
    run_outcomes(monkeypatch, [("https://a.com/h", DOWN)])

    now = monitor.datetime.now(monitor.dt_timezone.utc)
    summary = monitor.build_summary(now)

    assert "Health: 2 runs, 1 with failures" in summary
    assert "failing: p https://a.com/h" in summary
    assert "Pages" not in summary


def test_summary_without_data(state_dir):
    now = monitor.datetime.now(monitor.dt_timezone.utc)
    assert "No monitoring data found" in monitor.build_summary(now)


def test_recovery_list_is_capped(state_dir, monkeypatch):
    urls = [f"https://a.com/{i}" for i in range(25)]
    run_outcomes(monkeypatch, [(u, DOWN) for u in urls])
    sent = run_outcomes(monkeypatch, [(u, UP) for u in urls])

    assert len(sent) == 1
    assert sent[0].count("(failing for") == monitor.MAX_DETAILED_PAGES
    assert "… and 15 more" in sent[0]
