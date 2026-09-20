import os
import json
import random
import time
from pathlib import Path

import feedparser
import requests
from google import genai

from extractor import extract_full_text, extract_image
from rewriter import rewrite_article
from telegraph_publisher import publish_to_telegraph
from poll_manager import should_send_poll, mark_poll_sent, load_poll_state
from wikipedia_source import get_random_wiki_article
from wiki_prompts import get_prompt_for_rubric, get_hashtags_for_rubric
from posted_manager import (
    load_posted, save_posted, is_posted, mark_posted,
    cleanup_old, normalize_url,
)
from telegram_history import (
    load_local_history, save_local_history,
    fetch_telegram_links, merge_history,
)

print("[bot] === BOT VERSION 11 (Тут и Там, больше источников) ЗАГРУЖЕНА ===")

# Больше источников для тревел-канала
RSS_FEEDS = [
    "https://lenta.ru/rss/news/travel",
    "https://lenta.ru/rss/articles/travel",
    "https://ria.ru/export/rss2/index.xml",
    "https://tass.ru/rss/v2.xml",
    "https://www.interfax.ru/rss.asp",
    "https://www.rbc.ru/rss/finance",
    "https://www.vedomosti.ru/rss/news",
    "https://www.forbes.ru/newrss.xml",
    "https://www.banki.ru/xml/news.rss",
    "https://frankmedia.ru/feed/",
    "https://thebell.io/feed/",
    "https://rueconomics.ru/rss",
    "https://1prime.ru/export/rss2/index.xml",
]

KEYWORDS = [
    "туризм", "путешеств", "тур", "отдых", "виза", "авиа",
    "отель", "курорт", "билет", "авиакомпания", "рейс",
    "направление", "страна", "город", "пляж", "экскурсия",
    "достопримечательн", "маршрут", "поездк", "отпуск",
    "кухн", "блюд", "ресторан", "отдыхающ",
]

BLOCKED_WORDS = [
    "убил", "убийств", "погиб", "погибл", "смерть", "умер",
    "утопул", "утопленник", "изнасил", "ограбил", "ограблени",
    "задержан", "арестован", "осужден", "тюрьм", "наркотик",
    "криминал", "происшеств", "катастроф", "крушени", "авари",
    "теракт", "дтп", "пожар", "утону", "зарезал", "застрелил",
    "избил", "избиени", "насили", "домогательств", "разврат",
    "путин", "кремл", "спецоперац", "военн", "арми", "оружи",
    "беспилотник", "дрон", "аэс", "конфликт", "обстрел",
    "мобилизац", "минобороны", "генштаб", "нато",
    "долин", "артист", "певиц", "актер", "звезд", "селебрит",
    "скандал",
]

MAX_POSTS_PER_RUN = 4
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
MIN_TEXT_LENGTH = 500
MAX_TEXT_LENGTH = 15000
DELAY_MIN = 180    # было 600 — уменьшаем
DELAY_MAX = 300    # было 1200
WIKI_PROBABILITY = 0.3

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

IMAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


def matches_keywords(text):
    return any(kw in text.lower() for kw in KEYWORDS)


def has_blocked_words(text):
    return any(bad in text.lower() for bad in BLOCKED_WORDS)


POLLS = {
    "Визы и документы": {"question": "Сталкивались с этим?",
        "options": ["Да", "Нет", "Планирую", "Не актуально"]},
    "Цены и билеты": {"question": "Готовы платить?",
        "options": ["Да", "Дорого", "Дёшево", "Не поеду"]},
    "Маршруты и направления": {"question": "Поехали бы сюда?",
        "options": ["Хочу! 🔥", "Подумаю", "Не моё", "Уже был(а)"]},
    "Авиа и транспорт": {"question": "Как предпочитаете?",
        "options": ["Самолёт", "Поезд", "Авто", "Автобус"]},
    "Отели и проживание": {"question": "Что важнее?",
        "options": ["Комфорт", "Цена", "Локация", "Сервис"]},
    "Блюда и кухня": {"question": "Попробовали бы?",
        "options": ["Уже пробовал(а) 🔥", "Обязательно", "Не моё", "Слышал(а)"]},
    "Достопримечательности": {"question": "Хотели бы увидеть?",
        "options": ["Да! ✨", "Интересно", "Уже видел(а)", "Не моё"]},
    "Интересные факты": {"question": "Знали об этом?",
        "options": ["Впервые", "Знал(а)", "Очевидно", "Интересно!"]},
    "_default": {"question": "Что думаете?",
        "options": ["Круто! 🔥", "Спорно", "Не моё", "Попробую"]},
}


def get_poll_for_rubric(rubric_name):
    return POLLS.get(rubric_name, POLLS["_default"])


def download_image(image_url):
    try:
        r = requests.get(image_url, headers=IMAGE_HEADERS, timeout=25, stream=True)
        if r.status_code != 200:
            return None, None
        ct = r.headers.get("Content-Type", "").lower()
        if "image" not in ct:
            return None, None
        data = r.content
        if len(data) < 5000 or len(data) > 10 * 1024 * 1024:
            return None, None
        ext = "png" if "png" in ct else ("webp" if "webp" in ct else "jpg")
        return data, "photo." + ext
    except Exception:
        return None, None


def send_photo_bytes(image_bytes, filename, caption):
    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendPhoto"
    files = {"photo": (filename, image_bytes)}
    data = {"chat_id": TELEGRAM_CHANNEL_ID, "caption": caption[:1024], "parse_mode": "HTML"}
    try:
        r = requests.post(url, data=data, files=files, timeout=60)
        return r.status_code == 200
    except Exception:
        return False


def send_message(text):
    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendMessage"
    payload = {"chat_id": TELEGRAM_CHANNEL_ID, "text": text[:4000],
               "parse_mode": "HTML", "disable_web_page_preview": False}
    requests.post(url, json=payload, timeout=20)


def send_poll(question, options):
    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendPoll"
    payload = {"chat_id": TELEGRAM_CHANNEL_ID, "question": question[:300],
               "options": json.dumps(options, ensure_ascii=False),
               "is_anonymous": True, "allows_multiple_answers": False}
    requests.post(url, json=payload, timeout=20)


def build_post_text(rewritten, telegraph_url):
    title = rewritten["title"]
    teaser = rewritten.get("teaser", "")
    hashtags = rewritten.get("hashtags", "#ТутИТам #путешествия")
    rubric = rewritten.get("rubric_name", "")
    icons = {
        "Визы и документы": "🛂", "Цены и билеты": "💰",
        "Маршруты и направления": "🗺", "Авиа и транспорт": "✈️",
        "Отели и проживание": "🏨", "Блюда и кухня": "🍜",
        "Достопримечательности": "🏛", "Интересные факты": "💡",
    }
    icon = icons.get(rubric, "🌍")
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


def rewrite_wiki_article(wiki_data):
    rubric = wiki_data["rubric"]
    body = wiki_data["text"]
    title = wiki_data["title"]
    if wiki_data["lang"] == "en":
        from wiki_prompts import PROMPT_TRANSLATE
        prompt = PROMPT_TRANSLATE.format(title=title, body=body[:6000])
    else:
        prompt = get_prompt_for_rubric(rubric).format(title=title, body=body[:8000])

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception:
        return None

    from rewriter import FALLBACK_MODELS, try_model

    for m in [GEMINI_MODEL] + [x for x in FALLBACK_MODELS if x != GEMINI_MODEL]:
        result = try_model(client, m, prompt)
        if result:
            result["rubric_name"] = rubric
            result["hashtags"] = get_hashtags_for_rubric(rubric)
            result["style"] = "wiki"
            return result
    return None


def check_against_telegram(url, tg_history):
    if not url:
        return False
    normalized = normalize_url(url)
    for tg_url in tg_history:
        if normalize_url(tg_url) == normalized:
            return True
    return False


def publish_wiki_article(posted, tg_history):
    print("[wiki] Запуск тематического потока...")
    wiki_data = get_random_wiki_article()
    if not wiki_data:
        return False
    source_url = "https://ru.wikipedia.org/wiki/" + wiki_data["title"].replace(" ", "_")
    if is_posted(source_url, posted):
        print("[wiki] Дубликат в posted.json")
        return False
    if check_against_telegram(source_url, tg_history):
        print("[wiki] Дубликат в Telegram")
        mark_posted(source_url, posted)
        return False
    rewritten = rewrite_wiki_article(wiki_data)
    if not rewritten:
        return False
    telegraph_url = publish_to_telegraph(
        title=rewritten["title"], text=rewritten["text"], source_url=source_url)
    image_bytes, filename = None, None
    if wiki_data["image"]:
        image_bytes, filename = download_image(wiki_data["image"])
    caption = build_post_text(rewritten, telegraph_url)
    if DRY_RUN:
        print("[DRY_RUN][wiki] " + caption[:200])
    else:
        sent = False
        if image_bytes:
            if len(caption) > 1024:
                sent = send_photo_bytes(image_bytes, filename, caption[:1000] + "…")
                if sent and telegraph_url:
                    send_message("👉 <a href='" + telegraph_url + "'>Читать полностью</a>")
            else:
                sent = send_photo_bytes(image_bytes, filename, caption)
        if not sent:
            send_message(caption)
        if should_send_poll():
            poll = get_poll_for_rubric(rewritten.get("rubric_name", ""))
            time.sleep(3)
            send_poll(poll["question"], poll["options"])
            mark_poll_sent()
    mark_posted(source_url, posted)
    return True


def main():
    print("[bot] Запуск. DRY_RUN=" + str(DRY_RUN))
    print("[bot] Модель: " + str(GEMINI_MODEL))
    print("[bot] Источников RSS: " + str(len(RSS_FEEDS)))

    posted = load_posted()
    print("[bot] Записей в posted: " + str(len(posted)))

    tg_cache = load_local_history()
    fresh = fetch_telegram_links(TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, limit=100)
    tg_history = merge_history(tg_cache, fresh)
    save_local_history(tg_history)
    print("[bot] Ссылок в Telegram-истории: " + str(len(tg_history)))

    posted = cleanup_old(posted)

    if random.random() < WIKI_PROBABILITY:
        print("[bot] Режим: WIKI")
        if publish_wiki_article(posted, tg_history):
            save_posted(posted)
            print("[done] Опубликовано: 1 (wiki)")
            return
        print("[bot] WIKI не сработала, иду в RSS")

    print("[bot] Режим: RSS")
    published = 0

    for feed_url in RSS_FEEDS:
        if published >= MAX_POSTS_PER_RUN:
            break
        try:
            feed = feedparser.parse(feed_url)
        except Exception:
            continue

        print("[rss] " + feed_url + " — записей: " + str(len(feed.entries)))

        for entry in feed.entries:
            if published >= MAX_POSTS_PER_RUN:
                break

            link = entry.get("link", "")
            if not link:
                continue
            if is_posted(link, posted):
                continue
            if check_against_telegram(link, tg_history):
                print("[skip] Дубликат в Telegram: " + link[:80])
                mark_posted(link, posted)
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
                print("[skip] Не удалось извлечь текст: " + link[:80])
                continue
            text_len = len(full_text)
            if text_len < MIN_TEXT_LENGTH:
                print("[skip] Текст короткий (" + str(text_len) + "): " + link[:80])
                continue
            if text_len > MAX_TEXT_LENGTH:
                print("[skip] Текст длинный (" + str(text_len) + "): " + link[:80])
                continue
            if has_blocked_words(full_text):
                print("[skip] Заблокировано в тексте: " + title[:80])
                continue

            rewritten = rewrite_article(title, full_text, GEMINI_API_KEY, GEMINI_MODEL, summary=summary)
            if not rewritten:
                continue

            telegraph_url = publish_to_telegraph(
                title=rewritten["title"], text=rewritten["text"], source_url=link)

            image_url = extract_image(link)
            caption = build_post_text(rewritten, telegraph_url)

            if DRY_RUN:
                print("[DRY_RUN] " + caption[:150])
            else:
                sent = False
                if image_url:
                    ib, fn = download_image(image_url)
                    if ib:
                        if len(caption) > 1024:
                            sent = send_photo_bytes(ib, fn, caption[:1000] + "…")
                            if sent and telegraph_url:
                                send_message("👉 <a href='" + telegraph_url + "'>Читать полностью</a>")
                        else:
                            sent = send_photo_bytes(ib, fn, caption)
                if not sent:
                    send_message(caption)

                if should_send_poll():
                    poll = get_poll_for_rubric(rewritten.get("rubric_name", ""))
                    time.sleep(3)
                    send_poll(poll["question"], poll["options"])
                    mark_poll_sent()

                print("[bot] Опубликовано: " + rewritten["title"])

            mark_posted(link, posted)
            published += 1

            if published < MAX_POSTS_PER_RUN:
                time.sleep(random.randint(DELAY_MIN, DELAY_MAX))

    save_posted(posted)
    print("[done] Опубликовано: " + str(published))


if __name__ == "__main__":
    main()
