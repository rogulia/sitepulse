import pytest
import requests

import sitemap
from config import Settings

NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def urlset(*locs):
    entries = "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
    return f'<urlset xmlns="{NS}">{entries}</urlset>'.encode()


def index(*locs):
    entries = "".join(f"<sitemap><loc>{loc}</loc></sitemap>" for loc in locs)
    return f'<sitemapindex xmlns="{NS}">{entries}</sitemapindex>'.encode()


class Resp:
    def __init__(self, content=b"", status=200):
        self.content = content
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status} error")


def fake_get(pages):
    def get(url, **_):
        return pages.get(url) or Resp(status=404)

    return get


def test_plain_urlset(monkeypatch):
    pages = {"https://a.com/s.xml": Resp(urlset("https://a.com/", "https://a.com/x"))}
    monkeypatch.setattr(sitemap.requests, "get", fake_get(pages))

    result = sitemap.fetch_sitemap_urls("https://a.com/s.xml", Settings())

    assert result.urls == ["https://a.com/", "https://a.com/x"]
    assert result.errors == []


def test_sitemap_without_namespace(monkeypatch):
    body = b"<urlset><url><loc>https://a.com/</loc></url></urlset>"
    monkeypatch.setattr(
        sitemap.requests, "get", fake_get({"https://a.com/s.xml": Resp(body)})
    )
    assert sitemap.fetch_sitemap_urls("https://a.com/s.xml", Settings()).urls == [
        "https://a.com/"
    ]


def test_sitemap_index_is_followed_and_deduplicated(monkeypatch):
    pages = {
        "https://a.com/s.xml": Resp(
            index("https://a.com/1.xml", "https://a.com/2.xml")
        ),
        "https://a.com/1.xml": Resp(urlset("https://a.com/", "https://a.com/x")),
        "https://a.com/2.xml": Resp(urlset("https://a.com/x", "https://a.com/y")),
    }
    monkeypatch.setattr(sitemap.requests, "get", fake_get(pages))

    result = sitemap.fetch_sitemap_urls("https://a.com/s.xml", Settings())

    assert result.urls == ["https://a.com/", "https://a.com/x", "https://a.com/y"]


def test_child_failure_and_foreign_host_are_reported(monkeypatch):
    pages = {
        "https://a.com/s.xml": Resp(
            index(
                "https://a.com/ok.xml",
                "https://a.com/gone.xml",
                "https://evil.io/x.xml",
            )
        ),
        "https://a.com/ok.xml": Resp(urlset("https://a.com/")),
    }
    monkeypatch.setattr(sitemap.requests, "get", fake_get(pages))

    result = sitemap.fetch_sitemap_urls("https://a.com/s.xml", Settings())

    assert result.urls == ["https://a.com/"]
    assert len(result.errors) == 2
    assert any("gone.xml" in e for e in result.errors)
    assert any("different host" in e for e in result.errors)


def test_invalid_xml_is_an_error(monkeypatch):
    monkeypatch.setattr(
        sitemap.requests, "get", fake_get({"https://a.com/s.xml": Resp(b"<html>")})
    )
    result = sitemap.fetch_sitemap_urls("https://a.com/s.xml", Settings())
    assert result.urls == []
    assert result.errors


def test_parse_rejects_unknown_root():
    with pytest.raises(sitemap.SitemapError):
        sitemap.parse_sitemap(b"<rss></rss>")
