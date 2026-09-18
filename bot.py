import os
import json
import random
import time
from pathlib import Path

import feedparser
import requests

from extractor import extract_full_text, extract_image
from rewriter import rewrite_article
from telegraph_publisher import publish_to_telegraph

print("[bot] === BOT VERSION 6 ЗАГРУЖЕНА ===")

# ==== RSS ====
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

KEYWORDS = [
    "туризм", "путешеств", "тур", "отдых", "виза", "авиа",
    "отель", "курорт", "билет", "авиакомпания", "рейс",
    "направление", "страна", "город", "пляж", "экскурсия",
]

BLOCKED_WORDS = [
    "убил", "убийств", "погиб", "погибл", "смерть", "умер",
    "утопул", "утопленник", "изнасил", "ограбил", "ограблени",
    "задержан", "арестован", "осужден", "тюрьм", "наркотик",
    "криминал", "происшеств", "катастроф", "крушени", "авари",
    "теракт", "дтп", "пожар", "утону", "зарезал", "застрелил",
    "избил", "избиени", "насили", "домогательств", "разврат",
]

MAX_POSTS_PER_RUN = 3
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

MIN_TEXT_LENGTH = 500
MAX_TEXT_LENGTH = 15000

DELAY_MIN = 600
DELAY_MAX = 1200

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


def send_photo(photo_url, caption, reply_markup=None):
    """Отправляет фото с подписью в канал."""
    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendPhoto"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "photo": photo_url,
        "caption": caption[:1024],
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    r = requests.post(url, json=payload, timeout=30)
    if r.status_code != 200:
        print("[telegram] sendPhoto ошибка: " + str(r.status_code) + " " + r.text)
        return False
    return True


def send_message(text, reply_markup=None):
    """Отправляет текстовое сообщение в канал."""
    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    r = requests.post(url, json=payload, timeout=20)
    if r.status_code != 200:
        print("[telegram] sendMessage ошибка: " + str(r.status_code) + " " + r.text)


def build_reply_markup():
    """Инлайн-кнопки-реакции под постом."""
    return {
        "inline_keyboard": [
            [
                {"text": "🔥 Круто", "callback_data": "react_fire"},
                {"text": "🤔 Спорно", "callback_data": "react_think"},
            ],
            [
                {"text": "❤️ В избранное", "callback_data": "react_save"},
                {"text": "✈️ Хочу туда", "callback_data": "react_want"},
            ],
        ]
    }


def build_post_text(rewritten, telegraph_url):
    """Собирает текст поста с рубрикой, хэштегами и опросом."""
    title = rewritten["title"]
    teaser = rewritten.get("teaser", "")
    hashtags = rewritten.get("hashtags", "#ТутИТам #путешествия")
    rubric = rewritten.get("rubric_name", "")

    # Иконка рубрики
    rubric_icons = {
        "Визы и документы": "🛂",
        "Цены и билеты": "💰",
        "Маршруты и направления": "🗺",
        "Авиа и транспорт": "✈️",
        "Отели и проживание": "🏨",
    }
    icon = rubric_icons.get(rubric, "🌍")

    parts = []
    if rubric:
        parts.append(icon + " <b>" + rubric + "</b>")
        parts.append("")
    parts.append("<b>" + title + "</b>")
    parts.append("")
    if teaser:
        parts.append(teaser)
        parts.append("")

    if telegraph_url:
        parts.append("👉 <a href='" + telegraph_url + "'>Читать полностью</a>")
    parts.append("")
    parts.append(hashtags)

    return "\n".join(parts)


def main():
    print("[bot] Запуск. DRY_RUN=" + str(DRY_RUN))
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

            if not matches_keywords(title + " " + summary):
                continue

            if has_blocked_words(title + " " + summary):
                print("[skip] Заблокировано: " + title[:80])
                continue

            print("[process] " + link)

            full_text = extract_full_text(link)
            if not full_text:
                print("[skip] Не удалось извлечь текст: " + link)
                continue

            text_len = len(full_text)
            if text_len < MIN_TEXT_LENGTH:
                print("[skip] Текст короткий (" + str(text_len) + ")")
                continue
            if text_len > MAX_TEXT_LENGTH:
                print("[skip] Текст длинный (" + str(text_len) + ")")
                continue

            if has_blocked_words(full_text):
                print("[skip] Заблокировано в тексте: " + title[:80])
                continue

            # Рерайт (теперь с передачей summary для определения стиля)
            rewritten = rewrite_article(
                title, full_text, GEMINI_API_KEY, GEMINI_MODEL, summary=summary
            )
            if not rewritten or "title" not in rewritten or "text" not in rewritten:
                print("[skip] Рерайт не удался: " + link)
                continue

            # Telegraph
            telegraph_url = publish_to_telegraph(
                title=rewritten["title"],
                text=rewritten["text"],
                source_url=link,
            )

            # Картинка
            image_url = extract_image(link)
            if image_url:
                print("[bot] Картинка найдена: " + image_url[:80])
            else:
                print("[bot] Картинка не найдена, постим текстом")

            # Формируем пост
            caption = build_post_text(rewritten, telegraph_url)
            reply_markup = build_reply_markup()

            if DRY_RUN:
                print("[DRY_RUN] " + caption[:300] + "...")
            else:
                sent = False
                if image_url:
                    # Если подпись слишком длинная для фото — сокращаем
                    if len(caption) > 1024:
                        short = build_post_text(rewritten, telegraph_url)
                        # Обрезаем до 1000 и добавляем многоточие
                        caption_short = short[:1000] + "…"
                        sent = send_photo(image_url, caption_short, reply_markup)
                        if sent and telegraph_url:
                            # Дополняем ссылкой отдельным сообщением
                            send_message("👉 <a href='" + telegraph_url + "'>Читать полностью</a>")
                    else:
                        sent = send_photo(image_url, caption, reply_markup)

                if not sent:
                    send_message(caption, reply_markup)

                print("[bot] Опубликовано: " + rewritten["title"])

            posted.add(link)
            published += 1

            if published < MAX_POSTS_PER_RUN:
                delay = random.randint(DELAY_MIN, DELAY_MAX)
                print("[bot] Пауза " + str(delay) + " сек...")
                time.sleep(delay)

    save_posted(posted)
    print("[done] Опубликовано: " + str(published))


if __name__ == "__main__":
    main()
