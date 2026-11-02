import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests

from config import Settings

logger = logging.getLogger(__name__)

MAX_INDEX_DEPTH = 2


class SitemapError(Exception):
    pass


@dataclass
class SitemapResult:
    urls: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_sitemap(content: bytes) -> tuple[str, list[str]]:
    """Return ("urlset" | "sitemapindex", [loc, ...])."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise SitemapError(f"invalid XML: {e}") from None

    kind = _local_name(root.tag)
    if kind not in ("urlset", "sitemapindex"):
        raise SitemapError(f"unexpected root element <{kind}>")

    entry = "url" if kind == "urlset" else "sitemap"
    locs = []
    for element in root:
        if _local_name(element.tag) != entry:
            continue
        for child in element:
            if _local_name(child.tag) == "loc" and child.text and child.text.strip():
                locs.append(child.text.strip())
                break
    return kind, locs


def fetch_sitemap_urls(sitemap_url: str, settings: Settings) -> SitemapResult:
    """Collect page URLs from a sitemap or sitemap index.

    Child sitemaps of an index are fetched only from the index's own host.
    A failure fetching one child is recorded in `errors`; the rest is still returned.
    """
    result = SitemapResult()
    host = urlparse(sitemap_url).netloc
    visited = set()

    def visit(url: str, depth: int) -> None:
        if url in visited:
            return
        visited.add(url)
        try:
            response = requests.get(
                url, timeout=(settings.connect_timeout, settings.read_timeout)
            )
            response.raise_for_status()
            kind, locs = parse_sitemap(response.content)
        except (requests.RequestException, SitemapError) as e:
            result.errors.append(f"{url}: {type(e).__name__}: {e}")
            return

        if kind == "urlset":
            result.urls.extend(locs)
            return
        if depth >= MAX_INDEX_DEPTH:
            result.errors.append(f"{url}: sitemap index nested too deeply")
            return
        for child in locs:
            if urlparse(child).netloc != host:
                result.errors.append(f"{child}: child sitemap on a different host")
                continue
            visit(child, depth + 1)

    visit(sitemap_url, 0)
    result.urls = list(dict.fromkeys(result.urls))
    logger.info(f"Sitemap {sitemap_url}: {len(result.urls)} URLs")
    return result
