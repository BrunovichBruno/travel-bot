import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0 Safari/537.36"
}

# Селекторы основного текста для каждого источника.
# Если сайта нет в списке — используется fallback (все <p> внутри <article>).
SELECTORS = {
    "lenta.ru": "div.topic-body__content",
    "ria.ru": "div.article__body",
    "tass.ru": "div.text-content",
    "rbc.ru": "div.article__text",
    "tourprom.ru": "div.news-text",
    "atorus.ru": "div.field-item",
    "interfax.ru": "article",
}


def extract_full_text(url):
    """Скачивает страницу и вытаскивает основной текст статьи."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print("[extractor] Не удалось скачать " + url + ": " + str(e))
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    # Убираем мусор
    for tag in soup(["script", "style", "aside", "nav", "footer", "form"]):
        tag.decompose()

    domain = urlparse(url).netloc.replace("www.", "")
    selector = SELECTORS.get(domain)

    container = None
    if selector:
        container = soup.select_one(selector)

    if not container:
        container = soup.find("article") or soup

    paragraphs = container.find_all("p")
    text = "\n\n".join(
        p.get_text(strip=True)
        for p in paragraphs
        if len(p.get_text(strip=True)) > 40
    )
    return text or None
