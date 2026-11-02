from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from checks import domain as domain_mod
from checks import expiry
from checks.domain import LookupFailed, get_domain_info, parse_rdap, parse_whois
from checks.ssl_cert import CertInfo
from config import Config, Domain, Project, Settings


def test_parse_rdap_extracts_expiry_and_nameservers():
    info = parse_rdap(
        {
            "events": [
                {"eventAction": "registration", "eventDate": "2020-01-01T00:00:00Z"},
                {"eventAction": "expiration", "eventDate": "2027-03-01T12:30:00Z"},
            ],
            "nameservers": [
                {"ldhName": "NS2.Example.NET"},
                {"ldhName": "ns1.example.net"},
            ],
        }
    )
    assert info.expiry == date(2027, 3, 1)
    assert info.nameservers == ("ns1.example.net", "ns2.example.net")


def test_parse_rdap_without_expiration_fails():
    with pytest.raises(LookupFailed):
        parse_rdap(
            {
                "events": [
                    {"eventAction": "registration", "eventDate": "2020-01-01T00:00:00Z"}
                ]
            }
        )


def test_parse_whois_takes_earliest_date_and_handles_string_ns():
    w = SimpleNamespace(
        expiration_date=[datetime(2027, 5, 1), datetime(2027, 3, 1)],
        name_servers="NS1.Example.NET.",
    )
    info = parse_whois(w)
    assert info.expiry == date(2027, 3, 1)
    assert info.nameservers == ("ns1.example.net",)


def test_parse_whois_without_date_fails():
    with pytest.raises(LookupFailed):
        parse_whois(SimpleNamespace(expiration_date=None, name_servers=None))


def test_lookup_falls_back_to_whois_then_config(monkeypatch):
    def fail(_):
        raise RuntimeError("down")

    monkeypatch.setattr(domain_mod, "_lookup_rdap", fail)
    monkeypatch.setattr(domain_mod, "_lookup_whois", fail)

    info = get_domain_info("acme.com", "2027-03-01")
    assert (info.source, info.expiry) == ("config", date(2027, 3, 1))

    with pytest.raises(LookupFailed):
        get_domain_info("acme.com")


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (100, None),
        (60, expiry.WARNING),
        (15, expiry.WARNING),
        (14, expiry.CRITICAL),
        (-3, expiry.CRITICAL),
    ],
)
def test_classify(days, expected):
    assert expiry.classify(days, 60, 14) == expected


def make_config(domain):
    project = Project(
        "acme", "https://acme.com", "https://acme.com/sitemap.xml", (domain,)
    )
    return Config(Settings(), (project,))


def test_run_expiry_checks_reports_only_problems(monkeypatch):
    today = datetime.now(timezone.utc).date()
    info = domain_mod.DomainInfo(today + timedelta(days=10), ("ns.other.net",), "rdap")
    monkeypatch.setattr(expiry, "get_domain_info", lambda *_: info)

    def fake_cert(host):
        if host == "bad.acme.com":
            return CertInfo(host, None, None, "certificate invalid: expired")
        expires = datetime.now(timezone.utc) + timedelta(days=200)
        return CertInfo(host, expires, 200)

    monkeypatch.setattr(expiry, "check_certificate", fake_cert)

    domain = Domain("acme.com", ("acme.com", "bad.acme.com"), ("ns.mine.net",))
    findings = expiry.run_expiry_checks(make_config(domain))

    by_subject = {(f.subject, f.level) for f in findings}
    assert ("acme.com", expiry.CRITICAL) in by_subject
    assert ("acme.com", expiry.WARNING) in by_subject
    assert ("bad.acme.com", expiry.CRITICAL) in by_subject
    assert all(
        f.subject != "acme.com" or f.level in (expiry.CRITICAL, expiry.WARNING)
        for f in findings
    )


def test_format_report_escapes_html_and_skips_empty():
    now = datetime(2026, 11, 2, 9, 5, tzinfo=timezone.utc)
    assert expiry.format_report([], now) is None

    report = expiry.format_report(
        [expiry.Finding("a&b", "x.com", expiry.CRITICAL, "SSL <bad>")], now
    )
    assert report.startswith("📅 Expiry check 02.11.2026 09:05 UTC\n\n")
    assert "<b>a&amp;b</b>" in report
    assert "SSL &lt;bad&gt;" in report
