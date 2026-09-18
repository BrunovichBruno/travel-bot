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

print("[bot] === BOT VERSION 10 ЗАГРУЖЕНА (wiki + rss) ===")

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

# Вероятность, что текущий запуск будет Википедией, а не RSS
WIKI_PROBABILITY = 0.3

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

POSTED_FILE = Path("posted.json")

IMAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
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
    "Блюда и кухня": {
        "question": "Попробовали бы?",
        "options": ["Уже пробовал(а) 🔥", "Обязательно попробую", "Не моё", "Что-то слышал(а)"],
    },
    "Достопримечательности": {
        "question": "Хотели бы увидеть это?",
        "options": ["Да, мечтаю! ✨", "Интересно, но не сейчас", "Уже видел(а)", "Не моё"],
    },
    "Интересные факты": {
        "question": "Знали об этом?",
        "options": ["Впервые слышу!", "Знал(а), но забыл(а)", "Это очевидно", "Интересно!"],
    },
    "_default": {
        "question": "Что думаете об этом?",
        "options": ["Круто! 🔥", "Интересно, но спорно", "Не моё", "Хочу попробовать"],
    },
}


def get_poll_for_rubric(rubric_name):
    return POLLS.get(rubric_name, POLLS["_default"])


def download_image(image_url):
    try:
        print("[image] Скачиваю: " + image_url[:100])
        r = requests.get(image_url, headers=IMAGE_HEADERS, timeout=25, stream=True)
        if r.status_code != 200:
            print("[image] HTTP " + str(r.status_code))
            return None, None
        content_type = r.headers.get("Content-Type", "").lower()
        if "image" not in content_type:
            print("[image] Не картинка: " + content_type)
            return None, None
        data = r.content
        size = len(data)
        print("[image] Размер: " + str(size) + " байт")
        if size < 5000 or size > 10 * 1024 * 1024:
            print("[image] Размер вне нормы")
            return None, None
        ext = "jpg"
        if "png" in content_type:
            ext = "png"
        elif "webp" in content_type:
            ext = "webp"
        return data, "photo." + ext
    except Exception as e:
        print("[image] Ошибка: " + str(e))
        return None, None


def send_photo_bytes(image_bytes, filename, caption):
    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendPhoto"
    files = {"photo": (filename, image_bytes)}
    data = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "caption": caption[:1024],
        "parse_mode": "HTML",
    }
    try:
        r = requests.post(url, data=data, files=files, timeout=60)
        if r.status_code != 200:
            print("[telegram] sendPhoto ошибка: " + str(r.status_code) + " " + r.text[:200])
            return False
        print("[telegram] Фото отправлено")
        return True
    except Exception as e:
        print("[telegram] sendPhoto исключение: " + str(e))
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
        print("[telegram] sendMessage ошибка: " + str(r.status_code) + " " + r.text[:200])


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
        print("[telegram] sendPoll ошибка: " + str(r.status_code))
    else:
        print("[telegram] Опрос отправлен")


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
        "Блюда и кухня": "🍜",
        "Достопримечательности": "🏛",
        "Интересные факты": "💡",
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


def rewrite_wiki_article(wiki_data):
    """Рерайт статьи из Википедии с промптом под рубрику."""
    rubric = wiki_data["rubric"]
    prompt_template = get_prompt_for_rubric(rubric)

    # Если статья на английском — сначала переводим, потом рерайтим
    body = wiki_data["text"]
    title = wiki_data["title"]

    if wiki_data["lang"] == "en":
        print("[wiki] Статья на английском, перевожу...")
        # Используем промпт перевода
        from wiki_prompts import PROMPT_TRANSLATE
        prompt = PROMPT_TRANSLATE.format(title=title, body=body[:6000])
    else:
        prompt = prompt_template.format(title=title, body=body[:8000])

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print("[wiki] Ошибка клиента: " + str(e))
        return None

    # Пробуем модели
    from rewriter import FALLBACK_MODELS, try_model

    models_to_try = [GEMINI_MODEL] + [m for m in FALLBACK_MODELS if m != GEMINI_MODEL]

    for m in models_to_try:
        result = try_model(client, m, prompt)
        if result is not None:
            result["rubric_name"] = rubric
            result["hashtags"] = get_hashtags_for_rubric(rubric)
            result["style"] = "wiki"
            result["source_url"] = "https://ru.wikipedia.org/wiki/" + title.replace(" ", "_")
            return result

    print("[wiki] Все модели не сработали")
    return None


def publish_wiki_article(posted):
    """Публикует одну тематическую статью из Википедии."""
    print("[wiki] Запуск тематического потока...")
    wiki_data = get_random_wiki_article()
    if not wiki_data:
        print("[wiki] Не удалось получить статью")
        return False

    # Проверка на дубликат
    source_url = "https://ru.wikipedia.org/wiki/" + wiki_data["title"].replace(" ", "_")
    if source_url in posted:
        print("[wiki] Дубликат: " + wiki_data["title"])
        return False

    print("[wiki] Статья: " + wiki_data["title"] + " | Рубрика: " + wiki_data["rubric"])

    rewritten = rewrite_wiki_article(wiki_data)
    if not rewritten:
        print("[wiki] Рерайт не удался")
        return False

    # Telegraph
    telegraph_url = publish_to_telegraph(
        title=rewritten["title"],
        text=rewritten["text"],
        source_url=source_url,
    )

    # Картинка из Википедии
    image_bytes = None
    filename = None
    if wiki_data["image"]:
        image_bytes, filename = download_image(wiki_data["image"])
        if image_bytes:
            print("[wiki] Картинка из Википедии скачана")
        else:
            print("[wiki] Картинка не скачалась, постим без неё")

    caption = build_post_text(rewritten, telegraph_url)

    if DRY_RUN:
        print("[DRY_RUN][wiki] " + caption[:300] + "...")
    else:
        sent = False
        if image_bytes:
            if len(caption) > 1024:
                caption_short = caption[:1000] + "…"
                sent = send_photo_bytes(image_bytes, filename, caption_short)
                if sent and telegraph_url:
                    send_message("👉 <a href='" + telegraph_url + "'>Читать полностью</a>")
            else:
                sent = send_photo_bytes(image_bytes, filename, caption)
        if not sent:
            send_message(caption)

        # Опрос (если разрешён)
        if should_send_poll():
            poll = get_poll_for_rubric(rewritten.get("rubric_name", ""))
            time.sleep(3)
            send_poll(poll["question"], poll["options"])
            mark_poll_sent()

        print("[wiki] Опубликовано: " + rewritten["title"])

    posted.add(source_url)
    return True


def main():
    print("[bot] Запуск. DRY_RUN=" + str(DRY_RUN))
    print("[bot] Модель Gemini: " + str(GEMINI_MODEL))

    poll_state = load_poll_state()
    print("[bot] Опросов сегодня: " + str(poll_state["count"]) + "/3")

    posted = load_posted()

    # Решаем: этот запуск — Википедия или RSS?
    if random.random() < WIKI_PROBABILITY:
        print("[bot] Режим: ТЕМАТИЧЕСКАЯ СТАТЬЯ (Википедия)")
        success = publish_wiki_article(posted)
        if not success:
            print("[bot] Википедия не сработала, переключаюсь на RSS")
        else:
            save_posted(posted)
            print("[done] Опубликовано: 1 (wiki)")
            return

    # ==== ПОТОК RSS ====
    print("[bot] Режим: НОВОСТИ (RSS)")
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
                continue
            text_len = len(full_text)
            if text_len < MIN_TEXT_LENGTH or text_len > MAX_TEXT_LENGTH:
                continue
            if has_blocked_words(full_text):
                continue

            rewritten = rewrite_article(
                title, full_text, GEMINI_API_KEY, GEMINI_MODEL, summary=summary
            )
            if not rewritten:
                continue

            telegraph_url = publish_to_telegraph(
                title=rewritten["title"],
                text=rewritten["text"],
                source_url=link,
            )

            image_url = extract_image(link)
            caption = build_post_text(rewritten, telegraph_url)

            if DRY_RUN:
                print("[DRY_RUN] " + caption[:200] + "...")
            else:
                sent = False
                if image_url:
                    image_bytes, filename = download_image(image_url)
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
