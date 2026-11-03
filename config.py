import os
import tomllib
from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config.toml"
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = str(LOG_DIR / "website_monitor.log")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    min_response_size: int = 1000
    connect_timeout: int = 20
    read_timeout: int = 60
    slow_response_threshold: int = 10
    max_workers: int = 10
    notify_success: bool = False
    notify_warning: bool = False
    notify_error: bool = True
    domain_warn_days: int = 60
    domain_critical_days: int = 14
    ssl_warn_days: int = 21
    ssl_critical_days: int = 7
    log_retention_days: int = 10


@dataclass(frozen=True)
class Domain:
    name: str
    hosts: tuple[str, ...]
    nameservers: tuple[str, ...] = ()
    expiry_fallback: str | None = None


@dataclass(frozen=True)
class Project:
    name: str
    url: str
    sitemap: str
    domains: tuple[Domain, ...] = field(default_factory=tuple)
    health: tuple[str, ...] = ()


@dataclass(frozen=True)
class Config:
    settings: Settings
    projects: tuple[Project, ...]


def telegram_credentials() -> tuple[str, str]:
    load_dotenv()
    try:
        return os.environ["TELEGRAM_TOKEN"], os.environ["TELEGRAM_CHANNEL_ID"]
    except KeyError as e:
        raise ConfigError(f"Environment variable {e.args[0]} is required") from None


def _parse_settings(raw: dict) -> Settings:
    known = {f.name: f.type for f in fields(Settings)}
    unknown = set(raw) - set(known)
    if unknown:
        raise ConfigError(f"Unknown [settings] keys: {', '.join(sorted(unknown))}")
    for key, value in raw.items():
        expected = bool if known[key] in (bool, "bool") else int
        if type(value) is not expected:
            raise ConfigError(f"[settings] {key} must be {expected.__name__}")
    settings = Settings(**raw)
    if settings.domain_critical_days > settings.domain_warn_days:
        raise ConfigError("domain_critical_days must not exceed domain_warn_days")
    if settings.ssl_critical_days > settings.ssl_warn_days:
        raise ConfigError("ssl_critical_days must not exceed ssl_warn_days")
    return settings


def _require_str(raw: dict, key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where}: '{key}' is required and must be a string")
    return value.strip()


def _parse_str_list(
    raw: dict, key: str, where: str, lower: bool = True
) -> tuple[str, ...]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where}: '{key}' must be a list of strings")
    return tuple(
        (v.strip().lower() if lower else v.strip()) for v in value if v.strip()
    )


def _parse_domain(raw: dict, project: str) -> Domain:
    name = _require_str(raw, "name", f"project '{project}' domain").lower()
    where = f"project '{project}' domain '{name}'"
    hosts = _parse_str_list(raw, "hosts", where) if "hosts" in raw else (name,)
    expiry = raw.get("expiry_fallback")
    if isinstance(expiry, date):
        expiry = expiry.isoformat()
    if expiry is not None:
        try:
            date.fromisoformat(expiry)
        except (TypeError, ValueError):
            raise ConfigError(
                f"{where}: 'expiry_fallback' must be a date string YYYY-MM-DD"
            ) from None
    return Domain(
        name=name,
        hosts=hosts,
        nameservers=_parse_str_list(raw, "nameservers", where),
        expiry_fallback=expiry,
    )


def _parse_project(raw: dict) -> Project:
    name = _require_str(raw, "name", "project")
    url = _require_str(raw, "url", f"project '{name}'").rstrip("/")
    sitemap = raw.get("sitemap") or f"{url}/sitemap.xml"
    domains = tuple(_parse_domain(d, name) for d in raw.get("domain", []))
    health = _parse_str_list(raw, "health", f"project '{name}'", lower=False)
    for health_url in health:
        if not health_url.startswith(("http://", "https://")):
            raise ConfigError(
                f"project '{name}': health URL must start with http:// or https://"
            )
    return Project(name=name, url=url, sitemap=sitemap, domains=domains, health=health)


def load_config(path: str | Path | None = None) -> Config:
    config_path = Path(
        path or os.environ.get("SITEPULSE_CONFIG") or DEFAULT_CONFIG_PATH
    )
    try:
        with open(config_path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {config_path}") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Invalid TOML in {config_path}: {e}") from None

    projects = tuple(_parse_project(p) for p in raw.get("project", []))
    if not projects:
        raise ConfigError("At least one [[project]] is required")
    names = [p.name for p in projects]
    if len(set(names)) != len(names):
        raise ConfigError("Project names must be unique")

    return Config(settings=_parse_settings(raw.get("settings", {})), projects=projects)
