from __future__ import annotations

import json
import re
from typing import Any

import requests

PAGE_URL = "https://waytoagi.feishu.cn/wiki/QPe5w5g7UisbEkkow8XcDmOpn8e"
FEISHU_BASE_URL = "https://waytoagi.feishu.cn"
RECORD_START_RE = re.compile(r'(?<!\\)\{"id":"([A-Za-z0-9]+)","version":')


def fetch_html() -> str:
    response = requests.get(
        PAGE_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    response.raise_for_status()
    response.encoding = response.encoding or response.apparent_encoding
    return response.text


def _extract_json_object(source: str, marker: str) -> Any:
    marker_index = source.rfind(marker)
    if marker_index == -1:
        raise ValueError(f"marker not found: {marker}")

    brace_start = source.find("{", marker_index + len(marker))
    if brace_start == -1:
        raise ValueError(f"opening brace not found after marker: {marker}")

    return _extract_json_object_from_index(source, brace_start)


def _extract_json_object_from_index(source: str, brace_start: int) -> Any:
    if brace_start < 0 or brace_start >= len(source):
        raise ValueError(f"invalid brace start: {brace_start}")

    depth = 0
    in_string = False
    escape = False

    for index in range(brace_start, len(source)):
        char = source[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(source[brace_start : index + 1])

    raise ValueError(f"unterminated JSON object starting at index: {brace_start}")


def _extract_records(source: str) -> dict[str, Any]:
    records: dict[str, Any] = {}

    for match in RECORD_START_RE.finditer(source):
        record_id = match.group(1)
        if record_id in records:
            continue

        try:
            record = _extract_json_object_from_index(source, match.start())
        except Exception as exc:  # noqa: BLE001
            print(f"WARNING: failed to parse record {record_id}: {exc}")
            continue

        if isinstance(record, dict) and record.get("id") == record_id:
            records[record_id] = record

    return records


def _find_page_root(records: dict[str, Any]) -> str:
    for record_id, record in records.items():
        data = record.get("data", {})
        if data.get("type") == "page":
            return record_id

    raise ValueError("cannot find page root")


def _belongs_to_any_section_child(records: dict[str, Any], record_id: str, section_child_ids: set[str]) -> bool:
    current_id = record_id
    visited: set[str] = set()

    while current_id and current_id not in visited:
        if current_id in section_child_ids:
            return True
        visited.add(current_id)
        record = records.get(current_id)
        if not isinstance(record, dict):
            return False
        current_id = record.get("data", {}).get("parent_id")

    return False


def _find_section_root(records: dict[str, Any]) -> str:
    for record_id, record in records.items():
        data = record.get("data", {})
        if data.get("type") != "heading1":
            continue

        text = data.get("text", {}).get("initialAttributedTexts", {}).get("text", {}).get("0", "")
        normalized_text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", text)
        if "近7日更新日志" in normalized_text or "更新日志" in normalized_text:
            return record_id

    raise ValueError("cannot find section root: 近 7 日更新日志")


def _clean_summary(text: str) -> str:
    cleaned = re.sub(r"^《\s*[^》]*\s*》\s*", "", text or "")
    return cleaned.strip()


def _parse_article_node(record: dict[str, Any]) -> dict[str, str] | None:
    data = record.get("data", {})
    if data.get("type") not in {"bullet", "text"}:
        return None

    apool = data.get("text", {}).get("apool", {}).get("numToAttrib", {})
    components: list[dict[str, Any]] = []
    for value in apool.values():
        if isinstance(value, list) and len(value) == 2 and value[0] == "inline-component":
            try:
                components.append(json.loads(value[1]))
            except Exception as exc:  # noqa: BLE001
                print(f"WARNING: failed to decode inline component for {record.get('id')}: {exc}")
                return None

    mention = next(
        (
            component
            for component in components
            if component.get("type") == "mention_doc"
            and component.get("data", {}).get("token")
        ),
        None,
    )
    if not mention:
        return None

    mention_data = mention.get("data", {})
    title = str(mention_data.get("title", "")).strip()
    token = str(mention_data.get("token", "")).strip()
    if not title or not token:
        return None

    summary_source = data.get("text", {}).get("initialAttributedTexts", {}).get("text", {}).get("0", "")
    summary = _clean_summary(summary_source)
    if not summary or summary.startswith("阅读更多"):
        return None

    return {
        "title": title,
        "url": f"{FEISHU_BASE_URL}/wiki/{token}",
        "summary": summary,
    }


def parse_articles(html: str) -> list[dict[str, str]]:
    records = _extract_records(html)

    section_root = _find_section_root(records)
    page_root = _find_page_root(records)
    page_children = records.get(page_root, {}).get("data", {}).get("children", [])
    if not isinstance(page_children, list) or section_root not in page_children:
        raise ValueError("cannot locate section root in page root children")

    section_index = page_children.index(section_root)
    section_child_ids: set[str] = set()
    for child_id in page_children[section_index + 1 :]:
        child_record = records.get(child_id, {})
        child_type = child_record.get("data", {}).get("type") if isinstance(child_record, dict) else None
        if child_type == "heading1":
            break
        if isinstance(child_id, str):
            section_child_ids.add(child_id)

    articles: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for record_id, record in records.items():
        if record_id == section_root or record_id == page_root:
            continue
        if not _belongs_to_any_section_child(records, record_id, section_child_ids):
            continue
        article = _parse_article_node(record)
        if not article:
            continue
        if article["url"] in seen_urls:
            continue
        seen_urls.add(article["url"])
        articles.append(article)

    return articles
