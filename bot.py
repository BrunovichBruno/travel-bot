import os
import json
import random
import time
from pathlib import Path

import feedparser
import requests

from extractor import extract_full_text
from rewriter import rewrite_article
from telegraph_publisher import publish_to_telegraph

# ==== НАСТРОЙКИ ====
RSS_FEEDS = [
    "https://lenta.ru/rss/news/travel",
    "https://lenta.ru/rss/articles/travel",
    "https://ria.ru/export/rss2/index.xml",
]

KEYWORDS = ["туризм", "путешеств", "тур", "отдых", "виза", "авиа", "отель", "курорт"]
MAX_POSTS_PER_RUN = 3
HASHTAGS = "#ТутИТам #путешествия #кудапоехать"
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

POSTED_FILE = Path("posted.json")


def load_posted():
    if POSTED_FILE.exists():
        try:
            return set(json.loads(POSTED_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_posted(posted):
    POSTED_FILE.write_text(
        json.dumps(sorted(posted), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def matches_keywords(text: str) -> bool:
    text = text.lower()
    return any(kw in text for kw in KEYWORDS)


def send_to_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    r = requests.post(url, json=payload, timeout=20)
    if r.status_code != 200:
        print(f"[telegram] Ошибка: {r.status_code} {r.text}")


def main():
    posted = load_posted()
    published = 0

    for feed_url in RSS_FEEDS:
        if published >= MAX_POSTS_PER_RUN:
            break
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"[rss] Упал фид {feed_url}: {e}")
            continue

        for entry in feed.entries:
            if published >= MAX_POSTS_PER_RUN:
                break

            link = entry.get("link", "")
            if not link or link in posted:
                continue

            title = entry.get("title", "")
            summary = entry.get("summary", "")

            if not matches_keywords(title + " " + summary):
                continue

            print(f"[process] {link}")
            full_text = extract_full_text(link)
            if not full_text or len(full_text) < 300:
                print(f"[skip] Мало текста: {link}")
                continue

            rewritten = rewrite_article(title, full_text, GEMINI_API_KEY, GEMINI_MODEL)
            if not rewritten or "title" not in rewritten or "text" not in rewritten:
                print(f"[skip] Рерайт не удался: {link}")
                continue

            telegraph_url = publish_to_telegraph(
                title=rewritten["title"],
                text=rewritten["text"],
                source_url=link,
            )

            if telegraph_url:
                post = (
                    f"<b>{rewritten['title']}</b>\n\n"
                    f"{rewritten.get('teaser', '')}\n\n"
                    f"👉 <a href='{telegraph_url}'>Читать полностью</a>\n\n"
                    f"{HASHTAGS}"
                )
            else:
                post = (
                    f"<b>{rewritten['title']}</b>\n\n"
                    f"{rewritten['text'][:3000]}\n\n"
                    f"Источник: {link}\n\n{HASHTAGS}"
                )

            if DRY_RUN:
                print(f"[DRY_RUN] {post[:300]}...")
            else:
                send_to_telegram(post)

            posted.add(link)
            published += 1
            time.sleep(random.randint(30, 120))

    save_posted(posted)
    print(f"[done] Опубликовано: {published}")


if __name__ == "__main__":
    main()
