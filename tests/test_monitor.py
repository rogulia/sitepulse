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
