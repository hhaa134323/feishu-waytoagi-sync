from __future__ import annotations

import re
from datetime import datetime
from html import unescape

import requests

# Substack archive API—the same endpoint that powers the /archive page in the
# browser. It returns only the publication's main feed (long-form podcasts +
# essay posts); the AINews daily roundups live in a separate sub-publication
# and are excluded by default. Belt+suspenders [AINews] skip remains below.
ARCHIVE_API = "https://www.latent.space/api/v1/archive"
MAX_ITEMS = 30


def _strip_html(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_post_date(raw: str) -> str:
    """Convert ISO datetime (e.g. '2026-05-21T15:00:00.000Z') to YYYY-MM-DD."""
    if not raw:
        return ""
    try:
        cleaned = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        return dt.strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return ""


def _pick_excerpt(item: dict) -> str:
    """Best-effort summary, preferring subtitle (Swyx fills it in) over
    description (often an open-loop teaser)."""
    for key in ("subtitle", "description", "search_engine_description"):
        value = item.get(key)
        if value:
            text = _strip_html(str(value))
            if text:
                return text
    return ""


def fetch_latent_space_articles() -> list[dict[str, str]]:
    response = requests.get(
        ARCHIVE_API,
        params={"sort": "new", "limit": MAX_ITEMS, "offset": 0},
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; info-tracking-sync/1.0)",
            "Accept": "application/json",
        },
        timeout=30,
    )
    response.raise_for_status()

    try:
        items = response.json()
    except ValueError:
        return []

    if not isinstance(items, list):
        return []

    articles: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        title = (item.get("title") or "").strip()
        url = (item.get("canonical_url") or "").strip()
        if not url:
            slug = (item.get("slug") or "").strip()
            if slug:
                url = f"https://www.latent.space/p/{slug}"

        if not title or not url:
            continue

        # Belt+suspenders: skip AINews if any leak in.
        if title.startswith("[AINews]"):
            continue

        articles.append(
            {
                "title": title,
                "url": url,
                "summary": _pick_excerpt(item),
                "published_date": _parse_post_date(item.get("post_date") or ""),
            }
        )

    return articles
