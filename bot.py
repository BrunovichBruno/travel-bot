"""
Автопостинг travel-новостей в Telegram-канал.
Полностью бесплатный стек: feedparser + Google Gemini API (рерайт) + Telegram Bot API.
Запускается по расписанию через GitHub Actions (см. .github/workflows/post.yml).
"""

import os
import re
import json
import time
import hashlib
import feedparser
import requests

# ---------------------------------------------------------------------------
# НАСТРОЙКИ — правьте под свою нишу
# ---------------------------------------------------------------------------

# Русскоязычные RSS-источники про путешествия.
# lenta.ru/rss/news/travel и lenta.ru/rss/articles/travel — официальные RSS
# рубрики "Путешествия" (см. lenta.ru/info/posts/export/).
# ria.ru — общая лента РИА Новости, фильтруется ключевыми словами ниже.
RSS_FEEDS = [
    "https://lenta.ru/rss/news/travel",
    "https://lenta.ru/rss/articles/travel",
    "https://ria.ru/export/rss2/index.xml",
]

# Ключевые слова для фильтрации (актуальны в первую очередь для ria.ru,
# у которой лента общая, а не только про путешествия).
# Для lenta.ru/rss/*/travel фильтр не нужен — там и так только про travel,
# но оставляем его как доп. страховку от нерелевантных статей.
KEYWORDS = [
    "путешеств", "туризм", "турист", "авиабилет", "виза", "отель",
    "отдых", "курорт", "перелет", "перелёт", "аэропорт", "круиз",
    "экскурси", "поездк", "самолет", "самолёт", "гостиниц",
]

# Сколько постов публиковать за один запуск скрипта (чтобы не заспамить канал)
MAX_POSTS_PER_RUN = 3

# Хэштеги, которые будут добавлены к каждому посту
HASHTAGS = "#путешествия #туризм"

# Файл, в котором храним хэши уже опубликованных записей (чтобы не дублировать)
POSTED_FILE = "posted.json"

# --- Рерайт через Google Gemini (бесплатный тариф) --------------------------
# Ключ получить бесплатно на https://aistudio.google.com/apikey (без карты)
# и положить в GitHub Secret с именем GEMINI_API_KEY.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
)

REWRITE_PROMPT = """Ты — редактор Telegram-канала про путешествия.
Тебе дан заголовок и краткое описание новости. Перепиши их своими словами
(не копируй фразы дословно), сделай живо и по-человечески, без канцелярита,
можно с лёгкой иронией. Не выдумывай факты, которых нет в исходнике.

Верни СТРОГО JSON без markdown-обёртки и без пояснений, в формате:
{{"title": "короткий цепляющий заголовок", "text": "текст поста 2-4 предложения"}}

Заголовок источника: {title}
Описание источника: {summary}
"""

# ---------------------------------------------------------------------------
# Служебные функции
# ---------------------------------------------------------------------------

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")  # например @my_travel_channel или -100xxxxxxxxxx


def load_posted():
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_posted(posted_set):
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(posted_set), f, ensure_ascii=False, indent=2)


def entry_hash(entry):
    """Уникальный идентификатор записи, чтобы не публиковать дубликаты."""
    key = entry.get("link") or entry.get("id") or entry.get("title", "")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def matches_keywords(entry):
    text = (entry.get("title", "") + " " + entry.get("summary", "")).lower()
    return any(kw.lower() in text for kw in KEYWORDS)


def clean_html(raw, max_len=400):
    text = re.sub(r"<[^>]+>", "", raw or "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "…"
    return text


def rewrite_with_gemini(title, summary):
    """
    Бесплатный рерайт текста через Google Gemini API.
    Возвращает (title, text) или None, если рерайт не удался
    (тогда используется исходный текст без рерайта).
    """
    if not GEMINI_API_KEY:
        return None

    prompt = REWRITE_PROMPT.format(title=title, summary=summary)
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    try:
        resp = requests.post(GEMINI_URL, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
        # На случай, если модель всё же обернула ответ в ```json ... ```
        raw_text = raw_text.strip().strip("`")
        raw_text = re.sub(r"^json\s*", "", raw_text, flags=re.IGNORECASE).strip()
        parsed = json.loads(raw_text)
        new_title = parsed.get("title", "").strip()
        new_text = parsed.get("text", "").strip()
        if new_title and new_text:
            return new_title, new_text
    except Exception as e:
        print(f"[WARN] Рерайт через Gemini не удался, использую оригинал: {e}")

    return None


def extract_image(entry):
    if "media_content" in entry and entry.media_content:
        return entry.media_content[0].get("url")
    if "media_thumbnail" in entry and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url")
    for link in entry.get("links", []):
        if link.get("type", "").startswith("image"):
            return link.get("href")
    return None


def build_message(entry, source_title):
    raw_title = entry.get("title", "").strip()
    raw_summary = clean_html(entry.get("summary", ""))
    url = entry.get("link", "")

    rewritten = rewrite_with_gemini(raw_title, raw_summary)
    if rewritten:
        title, body = rewritten
    else:
        title, body = raw_title, raw_summary

    text = f"✈️ <b>{title}</b>\n\n{body}\n\n🔗 Источник: {source_title}\n{url}\n\n{HASHTAGS}"
    return text


def send_to_telegram(text, image_url=None):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHANNEL_ID:
        raise RuntimeError("Не заданы TELEGRAM_BOT_TOKEN / TELEGRAM_CHANNEL_ID")

    if image_url:
        api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        payload = {
            "chat_id": TELEGRAM_CHANNEL_ID,
            "photo": image_url,
            "caption": text,
            "parse_mode": "HTML",
        }
    else:
        api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHANNEL_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }

    resp = requests.post(api_url, data=payload, timeout=30)
    if resp.status_code != 200:
        print(f"[ERROR] Telegram API: {resp.status_code} {resp.text}")
        if image_url:
            print("[INFO] Пробую отправить без изображения…")
            send_to_telegram(text, image_url=None)
    else:
        print("[OK] Пост опубликован")
    return resp


# ---------------------------------------------------------------------------
# Основная логика
# ---------------------------------------------------------------------------

def main():
    posted = load_posted()
    new_posts_count = 0

    print(f"[INFO] Рерайт через Gemini: {'включён' if GEMINI_API_KEY else 'выключен (нет GEMINI_API_KEY)'}")

    for feed_url in RSS_FEEDS:
        if new_posts_count >= MAX_POSTS_PER_RUN:
            break

        print(f"[INFO] Читаю ленту: {feed_url}")
        feed = feedparser.parse(feed_url)
        source_title = feed.feed.get("title", feed_url)

        for entry in feed.entries:
            if new_posts_count >= MAX_POSTS_PER_RUN:
                break

            h = entry_hash(entry)
            if h in posted:
                continue
            if not matches_keywords(entry):
                continue

            text = build_message(entry, source_title)
            image_url = extract_image(entry)

            try:
                send_to_telegram(text, image_url)
                posted.add(h)
                new_posts_count += 1
                time.sleep(2)  # небольшая пауза между постами / запросами к Gemini
            except Exception as e:
                print(f"[ERROR] Не удалось опубликовать: {e}")

    save_posted(posted)
    print(f"[DONE] Опубликовано новых постов: {new_posts_count}")


if __name__ == "__main__":
    main()
