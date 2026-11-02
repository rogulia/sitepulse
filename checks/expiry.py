import html
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timezone

from checks.domain import get_domain_info
from checks.ssl_cert import check_certificate
from config import Config, Domain, Project, Settings

logger = logging.getLogger(__name__)

CRITICAL = "critical"
WARNING = "warning"
_SEVERITY = {WARNING: 1, CRITICAL: 2}
_EMOJI = {WARNING: "⚠️", CRITICAL: "🚨"}


@dataclass(frozen=True)
class Finding:
    project: str
    subject: str
    level: str
    text: str


def classify(days_left: int, warn_days: int, critical_days: int) -> str | None:
    if days_left <= critical_days:
        return CRITICAL
    if days_left <= warn_days:
        return WARNING
    return None


def _format_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _days_phrase(days_left: int) -> str:
    if days_left < 0:
        return f"expired {-days_left} days ago"
    return f"expires in {days_left} days"


def check_domain_registration(
    project: Project, domain: Domain, settings: Settings
) -> list[Finding]:
    try:
        info = get_domain_info(domain.name, domain.expiry_fallback)
    except Exception as e:
        return [
            Finding(
                project.name,
                domain.name,
                CRITICAL,
                f"registration check failed: {e}",
            )
        ]

    logger.info(f"Domain {domain.name}: expiry {info.expiry} (source {info.source})")
    findings = []
    days_left = (info.expiry - datetime.now(timezone.utc).date()).days
    level = classify(
        days_left, settings.domain_warn_days, settings.domain_critical_days
    )
    if level:
        findings.append(
            Finding(
                project.name,
                domain.name,
                level,
                f"registration {_days_phrase(days_left)} ({_format_date(info.expiry)})",
            )
        )

    if domain.nameservers and info.nameservers:
        if not set(domain.nameservers) & set(info.nameservers):
            findings.append(
                Finding(
                    project.name,
                    domain.name,
                    WARNING,
                    "nameservers differ from config: " + ", ".join(info.nameservers),
                )
            )
    return findings


def check_host_certificate(
    project: Project, host: str, settings: Settings
) -> list[Finding]:
    cert = check_certificate(host)
    if cert.error:
        return [Finding(project.name, host, CRITICAL, f"SSL {cert.error}")]

    logger.info(f"SSL {host}: {cert.days_left} days left")
    level = classify(cert.days_left, settings.ssl_warn_days, settings.ssl_critical_days)
    if not level:
        return []
    return [
        Finding(
            project.name,
            host,
            level,
            f"SSL certificate {_days_phrase(cert.days_left)} "
            f"({_format_date(cert.expires.date())})",
        )
    ]


def run_expiry_checks(config: Config) -> list[Finding]:
    settings = config.settings
    with ThreadPoolExecutor(max_workers=settings.max_workers) as executor:
        futures = []
        for project in config.projects:
            for domain in project.domains:
                futures.append(
                    executor.submit(
                        check_domain_registration, project, domain, settings
                    )
                )
                for host in domain.hosts:
                    futures.append(
                        executor.submit(check_host_certificate, project, host, settings)
                    )
        return [finding for future in futures for finding in future.result()]


def format_report(findings: list[Finding], now: datetime) -> str | None:
    if not findings:
        return None

    by_project = defaultdict(list)
    for finding in findings:
        by_project[finding.project].append(finding)

    blocks = []
    for project, items in by_project.items():
        worst = max(items, key=lambda f: _SEVERITY[f.level]).level
        lines = [f"{_EMOJI[worst]} <b>{html.escape(project)}</b>"]
        for item in sorted(items, key=lambda f: -_SEVERITY[f.level]):
            lines.append(f"- {html.escape(item.subject)}: {html.escape(item.text)}")
        blocks.append("\n".join(lines))

    header = f"📅 Expiry check {now.strftime('%d.%m.%Y %H:%M')} UTC"
    return header + "\n\n" + "\n\n".join(blocks)
