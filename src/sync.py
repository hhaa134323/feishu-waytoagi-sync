from __future__ import annotations

import os
import traceback

from notion_client import Client

from fetch import fetch_html, parse_articles

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DB_ID = os.environ["NOTION_DB_ID"]

notion = Client(auth=NOTION_TOKEN)


def get_existing_urls() -> set[str]:
    urls: set[str] = set()
    cursor = None

    while True:
        response = notion.databases.query(
            database_id=NOTION_DB_ID,
            start_cursor=cursor,
            page_size=100,
        )

        for row in response["results"]:
            link = row["properties"]["原文链接"].get("url")
            if link:
                urls.add(link)

        if not response["has_more"]:
            break

        cursor = response["next_cursor"]

    return urls


def create_page(article: dict[str, str]) -> None:
    notion.pages.create(
        parent={"database_id": NOTION_DB_ID},
        properties={
            "标题": {"title": [{"text": {"content": article["title"]}}]},
            "原文链接": {"url": article["url"]},
            "AI摘要": {"rich_text": [{"text": {"content": article["summary"][:2000]}}]},
            "来源": {"select": {"name": "waytoagi"}},
            "我的决定": {"status": {"name": "📋 待审"}},
        },
    )


def main() -> None:
    html = fetch_html()
    articles = parse_articles(html)
    existing_urls = get_existing_urls()
    new_articles = [article for article in articles if article["url"] not in existing_urls]

    print(f"飞书 {len(articles)} 篇 / 新增 {len(new_articles)} 篇")

    for article in new_articles:
        try:
            create_page(article)
            print(f"✅ {article['title']}")
        except Exception:  # noqa: BLE001
            print(f"❌ {article['title']}")
            traceback.print_exc()


if __name__ == "__main__":
    main()
