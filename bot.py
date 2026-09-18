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
import datetime
import feedparser
import requests

# ---------------------------------------------------------------------------
# НАСТРОЙКИ — правьте под свою нишу
# ---------------------------------------------------------------------------

# RSS-источники про путешествия. Можно смешивать русскоязычные и
# иностранные — Gemini сам переведёт и перепишет текст на русский
# (см. REWRITE_PROMPT ниже).
#
# Русскоязычные:
# lenta.ru/rss/news/travel и lenta.ru/rss/articles/travel — официальные RSS
# рубрики "Путешествия" (см. lenta.ru/info/posts/export/).
# ria.ru — общая лента РИА Новости, фильтруется ключевыми словами ниже.
#
# Зарубежные (англоязычные travel-издания):
RSS_FEEDS = [
    "https://lenta.ru/rss/news/travel",
    "https://lenta.ru/rss/articles/travel",
    "https://ria.ru/export/rss2/index.xml",
    "https://www.lonelyplanet.com/blog/feed",
    "https://www.travelandleisure.com/feeds/all.rss",
    "https://simpleflying.com/feed/",
    "https://www.thepointsguy.com/feed/",
]

# Ключевые слова для фильтрации — актуальны для общих лент (ria.ru), а также
# как страховка для остальных источников. Английские слова добавлены для
# иностранных лент.
KEYWORDS = [
    "путешеств", "туризм", "турист", "авиабилет", "виза", "отель",
    "отдых", "курорт", "перелет", "перелёт", "аэропорт", "круиз",
    "экскурси", "поездк", "самолет", "самолёт", "гостиниц",
    "travel", "flight", "flights", "airline", "destination",
    "hotel", "visa", "trip", "vacation", "tourism", "airport",
]

# Сколько постов публиковать за один запуск скрипта (страховка от заспамливания
# в рамках одного запуска — реальный лимит теперь держит DAILY_POST_LIMIT ниже)
MAX_POSTS_PER_RUN = 5

# Сколько постов публиковать за сутки максимум (сквозной лимит, действует
# независимо от того, сколько раз в день запускается workflow)
DAILY_POST_LIMIT = 20

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
Тебе дан заголовок и краткое описание новости — они могут быть на любом
языке (английском, русском и т.д.). Твоя задача:
1. Если текст не на русском — переведи его по смыслу на русский.
2. Перепиши своими словами (не копируй и не переводи дословно фраза
   в фразу), сделай живо и по-человечески, без канцелярита, можно с лёгкой
   иронией.
3. Не выдумывай факты, которых нет в исходнике.
4. Результат должен быть ПОЛНОСТЬЮ на русском языке, независимо от языка
   источника.

Верни СТРОГО JSON без markdown-обёртки и без пояснений, в формате:
{{"title": "короткий цепляющий заголовок на русском", "text": "текст поста на русском, 2-4 предложения"}}

Заголовок источника: {title}
Описание источника: {summary}
"""

# --- Фото со стоков, если в самой RSS-записи картинки нет (бесплатно) -------
# Ключ получить бесплатно и мгновенно на https://www.pexels.com/api/
# (без карты, без модерации) и положить в GitHub Secret PEXELS_API_KEY.
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

# --- Поиск релевантного видео на YouTube (публикуется ссылкой, не файлом) ---
# Ключ получить в Google Cloud Console: console.cloud.google.com →
# включить "YouTube Data API v3" → Credentials → Create API key.
# Бесплатная квота (10 000 юнитов/день) с большим запасом хватает на такой
# объём постов. Положить в GitHub Secret YOUTUBE_API_KEY.
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")

# ---------------------------------------------------------------------------
# Служебные функции
# ---------------------------------------------------------------------------

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")  # например @my_travel_channel или -100xxxxxxxxxx


def today_str():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")


def load_state():
    """
    Формат файла: {"hashes": [...], "daily_date": "YYYY-MM-DD", "daily_count": N}
    Сохранена обратная совместимость со старым форматом (просто список хэшей).
    """
    if not os.path.exists(POSTED_FILE):
        return {"hashes": set(), "daily_date": today_str(), "daily_count": 0}

    with open(POSTED_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        # старый формат — просто список хэшей, без счётчика за день
        return {"hashes": set(data), "daily_date": today_str(), "daily_count": 0}

    state = {
        "hashes": set(data.get("hashes", [])),
        "daily_date": data.get("daily_date", today_str()),
        "daily_count": data.get("daily_count", 0),
    }
    # если сутки сменились — обнуляем счётчик за день
    if state["daily_date"] != today_str():
        state["daily_date"] = today_str()
        state["daily_count"] = 0
    return state


def save_state(state):
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "hashes": sorted(state["hashes"]),
                "daily_date": state["daily_date"],
                "daily_count": state["daily_count"],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


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
    """
    Ищем картинку прямо в RSS-записи — проверяем все распространённые
    варианты, которые используют разные сайты.
    """
    if "media_content" in entry and entry.media_content:
        for m in entry.media_content:
            if m.get("url"):
                return m["url"]
    if "media_thumbnail" in entry and entry.media_thumbnail:
        for m in entry.media_thumbnail:
            if m.get("url"):
                return m["url"]
    # enclosure (часто используется на Lonely Planet, Simple Flying и т.д.)
    for enc in entry.get("enclosures", []):
        if enc.get("type", "").startswith("image") and enc.get("href"):
            return enc["href"]
    for link in entry.get("links", []):
        if link.get("type", "").startswith("image") and link.get("href"):
            return link["href"]
    # первая картинка прямо в HTML описания/контента статьи
    html_blob = entry.get("summary", "") or ""
    if "content" in entry and entry.content:
        html_blob += " " + entry.content[0].get("value", "")
    match = re.search(r'<img[^>]+src="([^"]+)"', html_blob)
    if match:
        return match.group(1)
    return None


def find_stock_photo(query):
    """
    Бесплатный фолбэк, если в RSS-записи фото не нашлось: ищем подходящее
    стоковое фото на Pexels по ключевым словам заголовка.
    """
    if not PEXELS_API_KEY or not query:
        return None
    try:
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": 1, "orientation": "landscape"},
            headers={"Authorization": PEXELS_API_KEY},
            timeout=15,
        )
        resp.raise_for_status()
        photos = resp.json().get("photos", [])
        if photos:
            return photos[0]["src"]["large"]
    except Exception as e:
        print(f"[WARN] Поиск фото на Pexels не удался: {e}")
    return None


def find_youtube_video(query):
    """
    Ищем один релевантный ролик на YouTube по теме статьи.
    Возвращает ссылку на видео (не сам файл!) — публикуется отдельным
    сообщением, Telegram сам покажет превью с плеером.
    """
    if not YOUTUBE_API_KEY or not query:
        return None
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": 1,
                "relevanceLanguage": "ru",
                "safeSearch": "strict",
                "key": YOUTUBE_API_KEY,
            },
            timeout=15,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if items:
            video_id = items[0]["id"]["videoId"]
            return f"https://www.youtube.com/watch?v={video_id}"
    except Exception as e:
        print(f"[WARN] Поиск видео на YouTube не удался: {e}")
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

    image_url = extract_image(entry)
    if not image_url:
        # ищем по оригинальному (не переписанному) заголовку — в нём обычно
        # более буквальные и узнаваемые ключевые слова для поиска фото
        image_url = find_stock_photo(raw_title)

    video_url = find_youtube_video(raw_title)

    return text, image_url, video_url


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


def send_video_link(video_url):
    """Публикует ссылку на YouTube-видео отдельным сообщением — Telegram
    сам развернёт нативное превью с плеером."""
    text = f"🎥 Видео по теме:\n{video_url}"
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text,
        "disable_web_page_preview": False,
    }
    resp = requests.post(api_url, data=payload, timeout=30)
    if resp.status_code != 200:
        print(f"[ERROR] Не удалось отправить ссылку на видео: {resp.status_code} {resp.text}")
    else:
        print("[OK] Ссылка на видео опубликована")
    return resp


# ---------------------------------------------------------------------------
# Основная логика
# ---------------------------------------------------------------------------

def main():
    state = load_state()
    new_posts_count = 0

    remaining_today = DAILY_POST_LIMIT - state["daily_count"]
    run_limit = min(MAX_POSTS_PER_RUN, max(remaining_today, 0))

    print(f"[INFO] Рерайт через Gemini: {'включён' if GEMINI_API_KEY else 'выключен (нет GEMINI_API_KEY)'}")
    print(f"[INFO] Фото с Pexels (фолбэк): {'включено' if PEXELS_API_KEY else 'выключено (нет PEXELS_API_KEY)'}")
    print(f"[INFO] Поиск видео на YouTube: {'включён' if YOUTUBE_API_KEY else 'выключен (нет YOUTUBE_API_KEY)'}")
    print(f"[INFO] Опубликовано сегодня ({state['daily_date']}): {state['daily_count']} из {DAILY_POST_LIMIT}")

    if run_limit <= 0:
        print("[INFO] Дневной лимит постов уже исчерпан, выходим без публикаций.")
        save_state(state)
        return

    for feed_url in RSS_FEEDS:
        if new_posts_count >= run_limit:
            break

        print(f"[INFO] Читаю ленту: {feed_url}")
        feed = feedparser.parse(feed_url)
        source_title = feed.feed.get("title", feed_url)

        for entry in feed.entries:
            if new_posts_count >= run_limit:
                break

            h = entry_hash(entry)
            if h in state["hashes"]:
                continue
            if not matches_keywords(entry):
                continue

            text, image_url, video_url = build_message(entry, source_title)

            try:
                send_to_telegram(text, image_url)
                if video_url:
                    time.sleep(1)
                    send_video_link(video_url)
                state["hashes"].add(h)
                state["daily_count"] += 1
                new_posts_count += 1
                time.sleep(2)  # небольшая пауза между постами / запросами к Gemini
            except Exception as e:
                print(f"[ERROR] Не удалось опубликовать: {e}")

    save_state(state)
    print(f"[DONE] Опубликовано новых постов за этот запуск: {new_posts_count}")
    print(f"[DONE] Итого за сегодня: {state['daily_count']} из {DAILY_POST_LIMIT}")


if __name__ == "__main__":
    main()
