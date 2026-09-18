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

print("[bot] === BOT VERSION 8 ЗАГРУЖЕНА (скачивание картинок) ===")

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

# Заголовки, под которыми бот скачивает картинки
IMAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Referer": "https://www.google.com/",
}


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


# ==== ОПРОСЫ ПО РУБРИКАМ ====

POLLS = {
    "Визы и документы": {
        "question": "Сталкивались с этим при оформлении визы?",
        "options": ["Да, было", "Нет, всё прошло гладко", "Планирую скоро", "Пока не актуально"],
    },
    "Цены и билеты": {
        "question": "Готовы платить такие деньги?",
        "options": ["Да, это нормально", "Дорого, поищу дешевле", "Слишком дёшево, есть подвох", "Не поеду"],
    },
    "Маршруты и направления": {
        "question": "Поехали бы сюда?",
        "options": ["Уже хочу! 🔥", "Может быть, подумаю", "Не моё направление", "Уже был(а) там"],
    },
    "Авиа и транспорт": {
        "question": "Как предпочитаете путешествовать?",
        "options": ["Самолёт — быстро", "Поезд — романтично", "Авто — свободно", "Автобус — бюджетно"],
    },
    "Отели и проживание": {
        "question": "Что для вас важнее в отеле?",
        "options": ["Чистота и комфорт", "Цена", "Расположение", "Питание и сервис"],
    },
    "_default": {
        "question": "Что думаете об этом?",
        "options": ["Круто! 🔥", "Интересно, но спорно", "Не моё", "Хочу попробовать"],
    },
}


def get_poll_for_rubric(rubric_name):
    return POLLS.get(rubric_name, POLLS["_default"])


# ==== СКАЧИВАНИЕ КАРТИНКИ ====

def download_image(image_url):
    """Скачивает картинку и возвращает (bytes, filename) или (None, None)."""
    try:
        print("[image] Скачиваю: " + image_url[:100])
        r = requests.get(image_url, headers=IMAGE_HEADERS, timeout=25, stream=True)
        if r.status_code != 200:
            print("[image] HTTP " + str(r.status_code))
            return None, None

        content_type = r.headers.get("Content-Type", "").lower()
        if "image" not in content_type:
            print("[image] Не картинка, Content-Type: " + content_type)
            return None, None

        data = r.content
        size = len(data)
        print("[image] Размер: " + str(size) + " байт, тип: " + content_type)

        if size < 5000:
            print("[image] Слишком маленькая (<5KB), пропускаю")
            return None, None
        if size > 10 * 1024 * 1024:
            print("[image] Слишком большая (>10MB), пропускаю")
            return None, None

        # Определяем расширение
        if "jpeg" in content_type or "jpg" in content_type:
            ext = "jpg"
        elif "png" in content_type:
            ext = "png"
        elif "webp" in content_type:
            ext = "webp"
        else:
            ext = "jpg"

        return data, "photo." + ext

    except Exception as e:
        print("[image] Ошибка: " + type(e).__name__ + ": " + str(e))
        return None, None


# ==== ОТПРАВКА В TELEGRAM ====

def send_photo_bytes(image_bytes, filename, caption):
    """Отправляет скачанную картинку как файл в Telegram."""
    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendPhoto"
    files = {
        "photo": (filename, image_bytes),
    }
    data = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "caption": caption[:1024],
        "parse_mode": "HTML",
    }
    try:
        r = requests.post(url, data=data, files=files, timeout=60)
        if r.status_code != 200:
            print("[telegram] sendPhoto ошибка: " + str(r.status_code) + " " + r.text[:300])
            return False
        print("[telegram] Фото отправлено")
        return True
    except Exception as e:
        print("[telegram] sendPhoto исключение: " + type(e).__name__ + ": " + str(e))
        return False


def send_message(text):
    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    r = requests.post(url, json=payload, timeout=20)
    if r.status_code != 200:
        print("[telegram] sendMessage ошибка: " + str(r.status_code) + " " + r.text[:300])


def send_poll(question, options):
    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendPoll"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "question": question[:300],
        "options": json.dumps(options, ensure_ascii=False),
        "is_anonymous": True,
        "allows_multiple_answers": False,
    }
    r = requests.post(url, json=payload, timeout=20)
    if r.status_code != 200:
        print("[telegram] sendPoll ошибка: " + str(r.status_code) + " " + r.text[:300])
    else:
        print("[telegram] Опрос отправлен")


# ==== СБОРКА ПОСТА ====

def build_post_text(rewritten, telegraph_url):
    title = rewritten["title"]
    teaser = rewritten.get("teaser", "")
    hashtags = rewritten.get("hashtags", "#ТутИТам #путешествия")
    rubric = rewritten.get("rubric_name", "")

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

            rewritten = rewrite_article(
                title, full_text, GEMINI_API_KEY, GEMINI_MODEL, summary=summary
            )
            if not rewritten or "title" not in rewritten or "text" not in rewritten:
                print("[skip] Рерайт не удался: " + link)
                continue

            telegraph_url = publish_to_telegraph(
                title=rewritten["title"],
                text=rewritten["text"],
                source_url=link,
            )

            # Картинка
            image_url = extract_image(link)
            caption = build_post_text(rewritten, telegraph_url)

            if DRY_RUN:
                print("[DRY_RUN] Картинка: " + str(image_url))
                print("[DRY_RUN] " + caption[:300] + "...")
                poll = get_poll_for_rubric(rewritten.get("rubric_name", ""))
                print("[DRY_RUN] Опрос: " + poll["question"])
            else:
                sent = False

                if image_url:
                    image_bytes, filename = download_image(image_url)
                    if image_bytes:
                        if len(caption) > 1024:
                            caption_short = caption[:1000] + "…"
                            sent = send_photo_bytes(image_bytes, filename, caption_short)
                            if sent and telegraph_url:
                                send_message("👉 <a href='" + telegraph_url + "'>Читать полностью</a>")
                        else:
                            sent = send_photo_bytes(image_bytes, filename, caption)

                if not sent:
                    print("[bot] Постим текстом (без картинки)")
                    send_message(caption)

                poll = get_poll_for_rubric(rewritten.get("rubric_name", ""))
                time.sleep(3)
                send_poll(poll["question"], poll["options"])

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
