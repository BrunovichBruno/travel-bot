import random
import requests

print("[wiki] === WIKIPEDIA SOURCE v5 (тревел-журнал) ЗАГРУЖЕН ===")

WIKI_API = "https://ru.wikipedia.org/w/api.php"
WIKI_API_EN = "https://en.wikipedia.org/w/api.php"

HEADERS = {"User-Agent": "TravelBot/5.0 (contact@example.com)"}

WIKI_CATEGORIES = [
    # ===== КУХНЯ И БЛЮДА =====
    ("Национальные кухни", "Кухня и блюда", "ru"),
    ("Блюда по странам", "Кухня и блюда", "ru"),
    ("Традиционные блюда", "Кухня и блюда", "ru"),
    ("Кухни народов мира", "Кухня и блюда", "ru"),
    ("Десерты по странам", "Кухня и блюда", "ru"),

    # ===== НАПИТКИ =====
    ("Национальные напитки", "Напитки", "ru"),
    ("Вина по странам", "Напитки", "ru"),
    ("Пиво по странам", "Напитки", "ru"),
    ("Кофе", "Напитки", "ru"),
    ("Чай", "Напитки", "ru"),

    # ===== ДОСТОПРИМЕЧАТЕЛЬНОСТИ =====
    ("Достопримечательности по странам", "Достопримечательности", "ru"),
    ("Всемирное наследие", "Достопримечательности", "ru"),
    ("Туристические объекты", "Достопримечательности", "ru"),
    ("Музеи по странам", "Достопримечательности", "ru"),
    ("Храмы и соборы", "Достопримечательности", "ru"),
    ("Замки и крепости", "Достопримечательности", "ru"),

    # ===== ГОРОДА =====
    ("Города по странам", "Города и регионы", "ru"),
    ("Столицы", "Города и регионы", "ru"),
    ("Города-миллионеры", "Города и регионы", "ru"),

    # ===== КУРОРТЫ =====
    ("Курорты", "Курорты", "ru"),
    ("Санатории", "Курорты", "ru"),
    ("Спа-курорты", "Курорты", "ru"),

    # ===== ПРИРОДА =====
    ("Национальные парки", "Природа и парки", "ru"),
    ("Заповедники", "Природа и парки", "ru"),
    ("Леса", "Природа и парки", "ru"),

    # ===== ГОРЫ И ВОДОПАДЫ =====
    ("Горы по странам", "Горы и водопады", "ru"),
    ("Водопады", "Горы и водопады", "ru"),
    ("Вулканы", "Горы и водопады", "ru"),

    # ===== ОЗЁРА И РЕКИ =====
    ("Озёра", "Озёра и реки", "ru"),
    ("Реки", "Озёра и реки", "ru"),

    # ===== ПЛЯЖИ И ОСТРОВА =====
    ("Пляжи", "Пляжи и острова", "ru"),
    ("Острова", "Пляжи и острова", "ru"),

    # ===== КУЛЬТУРА =====
    ("Культура по странам", "Культура и традиции", "ru"),
    ("Традиции", "Культура и традиции", "ru"),
    ("Обычаи", "Культура и традиции", "ru"),

    # ===== ПРАЗДНИКИ =====
    ("Национальные праздники", "Праздники и фестивали", "ru"),
    ("Фестивали", "Праздники и фестивали", "ru"),
    ("Карнавалы", "Праздники и фестивали", "ru"),

    # ===== ИСТОРИЯ =====
    ("История по странам", "История и легенды", "ru"),
    ("Легенды", "История и легенды", "ru"),
    ("Мифология", "История и легенды", "ru"),

    # ===== АНГЛИЙСКИЕ =====
    ("National dishes", "Кухня и блюда", "en"),
    ("World Heritage Sites", "Достопримечательности", "en"),
    ("Tourist attractions", "Достопримечательности", "en"),
    ("Cities by country", "Города и регионы", "en"),
    ("National parks", "Природа и парки", "en"),
    ("Beaches", "Пляжи и острова", "en"),
    ("Islands", "Пляжи и острова", "en"),
    ("Festivals", "Праздники и фестивали", "en"),
    ("Legends", "История и легенды", "en"),
]


def _get_category_members(api_url, category, limit=50):
    params = {"action": "query", "list": "categorymembers",
              "cmtitle": "Category:" + category, "cmlimit": str(limit),
              "cmnamespace": "0", "format": "json"}
    try:
        r = requests.get(api_url, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return [m["title"] for m in r.json().get("query", {}).get("categorymembers", [])]
    except Exception as e:
        print("[wiki] Ошибка категории " + category + ": " + str(e))
        return []


def _get_page_content(api_url, page_title):
    params = {"action": "query", "titles": page_title,
              "prop": "extracts|pageimages", "explaintext": "1",
              "piprop": "original", "format": "json"}
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
        members = _get_category_members(api_url, category, limit=50)
        if not members:
            continue
        random.shuffle(members)
        for page_title in members[:15]:
            text, image = _get_page_content(api_url, page_title)
            if text and len(text) > 800:
                print("[wiki] Нашёл: " + page_title + " (" + str(len(text)) + " симв.)")
                return {"title": page_title, "text": text[:8000], "image": image,
                        "category": category, "rubric": rubric, "lang": lang}
    print("[wiki] Ничего не нашёл")
    return None
