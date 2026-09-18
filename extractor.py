import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0 Safari/537.36"
}

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
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print("[extractor] Ошибка скачивания " + url + ": " + str(e))
        return None

    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "aside", "nav", "footer", "form"]):
        tag.decompose()

    domain = urlparse(url).netloc.replace("www.", "")
    selector = SELECTORS.get(domain)

    container = soup.select_one(selector) if selector else None
    if not container:
        container = soup.find("article") or soup

    paragraphs = container.find_all("p")
    text = "\n\n".join(
        p.get_text(strip=True)
        for p in paragraphs
        if len(p.get_text(strip=True)) > 40
    )
    return text or None


def extract_image(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception:
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        img = og["content"]
        if img.startswith("//"):
            img = "https:" + img
        elif img.startswith("/"):
            img = urljoin(url, img)
        return img

    tw = soup.find("meta", attrs={"name": "twitter:image"})
    if tw and tw.get("content"):
        img = tw["content"]
        if img.startswith("//"):
            img = "https:" + img
        elif img.startswith("/"):
            img = urljoin(url, img)
        return img

    for img_tag in soup.find_all("img"):
        src = img_tag.get("src") or img_tag.get("data-src")
        if not src:
            continue
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = urljoin(url, src)
        if any(x in src.lower() for x in ["icon", "logo", "sprite", "avatar", "1x1", "pixel"]):
            continue
        return src
    return None
