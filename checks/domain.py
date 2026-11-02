from dataclasses import dataclass
from datetime import date, datetime
from functools import cache

import requests
import whois

RDAP_BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
REQUEST_TIMEOUT = (10, 20)


class LookupFailed(Exception):
    pass


@dataclass(frozen=True)
class DomainInfo:
    expiry: date
    nameservers: tuple[str, ...]
    source: str


@cache
def _rdap_bootstrap() -> dict[str, str]:
    response = requests.get(RDAP_BOOTSTRAP_URL, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    tld_to_base = {}
    for tlds, urls in response.json()["services"]:
        for tld in tlds:
            tld_to_base[tld.lower()] = urls[0]
    return tld_to_base


def parse_rdap(data: dict) -> DomainInfo:
    expiry = None
    for event in data.get("events", []):
        if event.get("eventAction") == "expiration":
            expiry = datetime.fromisoformat(event["eventDate"]).date()
            break
    if expiry is None:
        raise LookupFailed("RDAP response has no expiration event")
    nameservers = tuple(
        sorted(
            ns["ldhName"].lower().rstrip(".")
            for ns in data.get("nameservers", [])
            if ns.get("ldhName")
        )
    )
    return DomainInfo(expiry=expiry, nameservers=nameservers, source="rdap")


def _lookup_rdap(domain: str) -> DomainInfo:
    tld = domain.rsplit(".", 1)[-1]
    base = _rdap_bootstrap().get(tld)
    if base is None:
        raise LookupFailed(f"No RDAP service for .{tld}")
    response = requests.get(
        f"{base.rstrip('/')}/domain/{domain}",
        timeout=REQUEST_TIMEOUT,
        headers={"Accept": "application/rdap+json"},
    )
    response.raise_for_status()
    return parse_rdap(response.json())


def parse_whois(w) -> DomainInfo:
    raw_expiry = w.expiration_date
    if isinstance(raw_expiry, list):
        raw_expiry = min(raw_expiry)
    if not isinstance(raw_expiry, datetime):
        raise LookupFailed("WHOIS response has no expiration date")

    raw_ns = w.name_servers or []
    if isinstance(raw_ns, str):
        raw_ns = [raw_ns]
    nameservers = tuple(sorted({ns.lower().rstrip(".") for ns in raw_ns}))
    return DomainInfo(expiry=raw_expiry.date(), nameservers=nameservers, source="whois")


def _lookup_whois(domain: str) -> DomainInfo:
    return parse_whois(whois.whois(domain))


def get_domain_info(domain: str, expiry_fallback: str | None = None) -> DomainInfo:
    errors = []
    for lookup in (_lookup_rdap, _lookup_whois):
        try:
            return lookup(domain)
        except Exception as e:
            errors.append(f"{lookup.__name__[8:]}: {type(e).__name__}: {e}")

    if expiry_fallback:
        return DomainInfo(
            expiry=date.fromisoformat(expiry_fallback), nameservers=(), source="config"
        )
    raise LookupFailed("; ".join(errors))
