import random
import requests

print("[wiki] === WIKIPEDIA SOURCE ЗАГРУЖЕН ===")

WIKI_API = "https://ru.wikipedia.org/w/api.php"
WIKI_API_EN = "https://en.wikipedia.org/w/api.php"

HEADERS = {
    "User-Agent": "TravelBot/1.0 (https://github.com/travel-bot; contact@example.com)"
}

WIKI_CATEGORIES = [
    ("Национальные кухни", "Блюда и кухня", "ru"),
    ("Блюда по странам", "Блюда и кухня", "ru"),
    ("Традиционные блюда", "Блюда и кухня", "ru"),
    ("Достопримечательности по странам", "Достопримечательности", "ru"),
    ("Всемирное наследие", "Достопримечательности", "ru"),
    ("Туристические объекты", "Достопримечательности", "ru"),
    ("Культура по странам", "Интересные факты", "ru"),
    ("Традиции", "Интересные факты", "ru"),
    ("National dishes", "Блюда и кухня", "en"),
    ("World Heritage Sites", "Достопримечательности", "en"),
]


def _get_category_members(api_url, category, limit=30):
    params = {
        "action": "query", "list": "categorymembers",
        "cmtitle": "Category:" + category, "cmlimit": str(limit),
        "cmnamespace": "0", "format": "json",
    }
    try:
        r = requests.get(api_url, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return [m["title"] for m in r.json().get("query", {}).get("categorymembers", [])]
    except Exception as e:
        print("[wiki] Ошибка категории " + category + ": " + str(e))
        return []


def _get_page_content(api_url, page_title):
    params = {
        "action": "query", "titles": page_title,
        "prop": "extracts|pageimages", "explaintext": "1",
        "piprop": "original", "format": "json",
    }
    try:
        r = requests.get(api_url, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        pages = r.json().get("query", {}).get("pages", {})
        for pid, pdata in pages.items():
            if pid == "-1":
                return None, None
            return pdata.get("extract", ""), pdata.get("original", {}).get("source")
    except Exception as e:
        print("[wiki] Ошибка страницы " + page_title + ": " + str(e))
    return None, None


def get_random_wiki_article():
    random.shuffle(WIKI_CATEGORIES)

    for category, rubric, lang in WIKI_CATEGORIES:
        api_url = WIKI_API if lang == "ru" else WIKI_API_EN
        print("[wiki] Категория: " + category + " (" + lang + ")")

        members = _get_category_members(api_url, category, limit=30)
        if not members:
            continue
        random.shuffle(members)

        for page_title in members[:10]:
            text, image = _get_page_content(api_url, page_title)
            if text and len(text) > 500:
                print("[wiki] Нашёл: " + page_title + " (" + str(len(text)) + " симв.)")
                return {
                    "title": page_title,
                    "text": text[:8000],
                    "image": image,
                    "category": category,
                    "rubric": rubric,
                    "lang": lang,
                }
    print("[wiki] Ничего не нашёл")
    return None
