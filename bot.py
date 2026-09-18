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

print("[bot] === BOT VERSION 5 ЗАГРУЖЕНА ===")

# ==== ИСТОЧНИКИ RSS ====
RSS_FEEDS = [
    "https://lenta.ru/rss/news/travel",
    "https://lenta.ru/rss/articles/travel",
    "https://ria.ru/export/rss2/index.xml",
    "https://www.tourprom.ru/rss/",
    "https://www.rbc.ru/rss/travel",
    "https://tass.ru/rss/v2.xml",
    "https://www.atorus.ru/rss/news.xml",
    "https://www.interfax.ru/rss.asp",
]

# ==== КЛЮЧЕВЫЕ СЛОВА (должны быть в тексте) ====
KEYWORDS = [
    "туризм", "путешеств", "тур", "отдых", "виза", "авиа",
    "отель", "курорт", "билет", "авиакомпания", "рейс",
    "направление", "страна", "город", "пляж", "экскурсия",
]

# ==== ЗАПРЕЩЁННЫЕ СЛОВА (если есть — пропускаем) ====
BLOCKED_WORDS = [
    "убил", "убийств", "погиб", "погибл", "смерть", "умер",
    "утопул", "утопленник", "изнасил", "ограбил", "ограблени",
    "задержан", "арестован", "осужден", "тюрьм", "наркотик",
    "криминал", "происшеств", "катастроф", "крушени", "авари",
    "теракт", "дтп", "пожар", "утону", "зарезал", "застрелил",
    "избил", "избиени", "насили", "домогательств", "разврат",
]

# ==== НАСТРОЙКИ ПУБЛИКАЦИИ ====
MAX_POSTS_PER_RUN = 3
HASHTAGS = "#ТутИТам #путешествия #кудапоехать"
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

MIN_TEXT_LENGTH = 500
MAX_TEXT_LENGTH = 15000

# Задержка между постами внутри одного запуска (в секундах)
DELAY_MIN = 600    # 10 минут
DELAY_MAX = 1200   # 20 минут

# ==== СЕКРЕТЫ ====
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

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


def matches_keywords(text):
    text = text.lower()
    return any(kw in text for kw in KEYWORDS)


def has_blocked_words(text):
    text = text.lower()
    return any(bad in text for bad in BLOCKED_WORDS)


def send_to_telegram(text):
    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    r = requests.post(url, json=payload, timeout=20)
    if r.status_code != 200:
        print("[telegram] Ошибка: " + str(r.status_code) + " " + r.text)


def main():
    print("[bot] Запуск. DRY_RUN=" + str(DRY_RUN))
    print("[bot] Gemini ключ задан: " + str(bool(GEMINI_API_KEY)))
    print("[bot] Telegram токен задан: " + str(bool(TELEGRAM_BOT_TOKEN)))
    print("[bot] Модель Gemini: " + str(GEMINI_MODEL))
    print("[bot] Источников RSS: " + str(len(RSS_FEEDS)))

    posted = load_posted()
    published = 0

    for feed_url in RSS_FEEDS:
        if published >= MAX_POSTS_PER_RUN:
            break

        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            print("[rss] Упал фид " + feed_url + ": " + str(e))
            continue

        print("[rss] " + feed_url + " — записей: " + str(len(feed.entries)))

        for entry in feed.entries:
            if published >= MAX_POSTS_PER_RUN:
                break

            link = entry.get("link", "")
            if not link or link in posted:
                continue

            title = entry.get("title", "")
            summary = entry.get("summary", "")

            # 1. Проверка ключевых слов
            if not matches_keywords(title + " " + summary):
                continue

            # 2. Проверка запрещённых слов
            if has_blocked_words(title + " " + summary):
                print("[skip] Заблокировано: " + title[:80])
                continue

            print("[process] " + link)

            # 3. Извлекаем полный текст
            full_text = extract_full_text(link)
            if not full_text:
                print("[skip] Не удалось извлечь текст: " + link)
                continue

            text_len = len(full_text)
            if text_len < MIN_TEXT_LENGTH:
                print("[skip] Текст слишком короткий (" + str(text_len) + "): " + link)
                continue
            if text_len > MAX_TEXT_LENGTH:
                print("[skip] Текст слишком длинный (" + str(text_len) + "): " + link)
                continue

            # 4. Проверяем полный текст на запрещённые слова
            if has_blocked_words(full_text):
                print("[skip] Заблокировано в тексте: " + title[:80])
                continue

            # 5. Рерайт
            rewritten = rewrite_article(title, full_text, GEMINI_API_KEY, GEMINI_MODEL)
            if not rewritten or "title" not in rewritten or "text" not in rewritten:
                print("[skip] Рерайт не удался: " + link)
                continue

            # 6. Telegraph
            telegraph_url = publish_to_telegraph(
                title=rewritten["title"],
                text=rewritten["text"],
                source_url=link,
            )

            # 7. Формируем пост
            if telegraph_url:
                post = (
                    "<b>" + rewritten["title"] + "</b>\n\n"
                    + rewritten.get("teaser", "") + "\n\n"
                    + "👉 <a href='" + telegraph_url + "'>Читать полностью</a>\n\n"
                    + HASHTAGS
                )
            else:
                post = (
                    "<b>" + rewritten["title"] + "</b>\n\n"
                    + rewritten["text"][:3000] + "\n\n"
                    + "Источник: " + link + "\n\n" + HASHTAGS
                )

            if DRY_RUN:
                print("[DRY_RUN] " + post[:300] + "...")
            else:
                send_to_telegram(post)
                print("[bot] Опубликовано: " + rewritten["title"])

            posted.add(link)
            published += 1

            # 8. Задержка между постами (только если публикуем не последний)
            if published < MAX_POSTS_PER_RUN:
                delay = random.randint(DELAY_MIN, DELAY_MAX)
                print("[bot] Пауза " + str(delay) + " секунд до следующего поста...")
                time.sleep(delay)

    save_posted(posted)
    print("[done] Опубликовано: " + str(published))


if __name__ == "__main__":
    main()
