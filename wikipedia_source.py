import random
import requests

print("[wiki] === WIKIPEDIA SOURCE ЗАГРУЖЕН ===")

WIKI_API = "https://ru.wikipedia.org/w/api.php"
WIKI_API_EN = "https://en.wikipedia.org/w/api.php"

HEADERS = {
    "User-Agent": "TravelBot/1.0 (https://github.com/your-repo; contact@example.com)"
}

# Категории Википедии для тематических статей
# Формат: (категория, рубрика_для_бота, язык)
WIKI_CATEGORIES = [
    # Блюда и кухня
    ("Национальные кухни", "Блюда и кухня", "ru"),
    ("Блюда по странам", "Блюда и кухня", "ru"),
    ("Традиционные блюда", "Блюда и кухня", "ru"),

    # Достопримечательности
    ("Достопримечательности по странам", "Достопримечательности", "ru"),
    ("Всемирное наследие", "Достопримечательности", "ru"),
    ("Туристические объекты", "Достопримечательности", "ru"),

    # Интересные факты
    ("Культура по странам", "Интересные факты", "ru"),
    ("Традиции", "Интересные факты", "ru"),
    ("Национальные символы", "Интересные факты", "ru"),

    # Английская вики (для перевода)
    ("National dishes", "Блюда и кухня", "en"),
    ("World Heritage Sites", "Достопримечательности", "en"),
    ("Tourist attractions", "Достопримечательности", "en"),
]


def _get_category_members(api_url, category, limit=50):
    """Возвращает список названий страниц в категории."""
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": "Category:" + category,
        "cmlimit": str(limit),
        "cmnamespace": "0",  # только статьи
        "format": "json",
    }
    try:
        r = requests.get(api_url, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        members = data.get("query", {}).get("categorymembers", [])
        return [m["title"] for m in members]
    except Exception as e:
        print("[wiki] Ошибка получения категории " + category + ": " + str(e))
        return []


def _get_page_content(api_url, page_title):
    """Возвращает текст страницы (plain text) и URL главной картинки."""
    params = {
        "action": "query",
        "titles": page_title,
        "prop": "extracts|pageimages",
        "explaintext": "1",
        "exintro": "0",
        "exsectionformat": "plain",
        "piprop": "original",
        "format": "json",
    }
    try:
        r = requests.get(api_url, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        for page_id, page_data in pages.items():
            if page_id == "-1":
                return None, None
            text = page_data.get("extract", "")
            image = page_data.get("original", {}).get("source", None)
            return text, image
    except Exception as e:
        print("[wiki] Ошибка получения страницы " + page_title + ": " + str(e))
    return None, None


def get_random_wiki_article():
    """
    Возвращает dict с полями:
    - title: заголовок статьи
    - text: полный текст (обрезка до 8000 символов)
    - image: URL картинки или None
    - category: категория (для отладки)
    - rubric: рубрика для бота (Блюда и кухня / Достопримечательности / Интересные факты)
    - lang: язык статьи (ru / en)
    """
    random.shuffle(WIKI_CATEGORIES)

    for category, rubric, lang in WIKI_CATEGORIES:
        api_url = WIKI_API if lang == "ru" else WIKI_API_EN
        print("[wiki] Пробую категорию: " + category + " (" + lang + ")")

        members = _get_category_members(api_url, category, limit=30)
        if not members:
            print("[wiki] Категория пуста: " + category)
            continue

        random.shuffle(members)

        for page_title in members[:10]:
            text, image = _get_page_content(api_url, page_title)
            if text and len(text) > 500:
                print("[wiki] Нашёл статью: " + page_title + " (" + str(len(text)) + " символов)")
                return {
                    "title": page_title,
                    "text": text[:8000],
                    "image": image,
                    "category": category,
                    "rubric": rubric,
                    "lang": lang,
                }
            else:
                print("[wiki] Пропускаю (короткая): " + page_title)

    print("[wiki] Не удалось найти подходящую статью")
    return None
