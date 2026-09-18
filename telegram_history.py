import json
import requests
from pathlib import Path
from bs4 import BeautifulSoup

print("[tg_history] === TELEGRAM HISTORY ЗАГРУЖЕН ===")

HISTORY_FILE = Path("telegram_history.json")


def load_local_history():
    if HISTORY_FILE.exists():
        try:
            return set(json.loads(HISTORY_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_local_history(urls):
    try:
        HISTORY_FILE.write_text(
            json.dumps(sorted(urls), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print("[tg_history] Ошибка сохранения: " + str(e))


def fetch_telegram_links(bot_token, channel_id, limit=100):
    if not channel_id:
        return set()

    username = channel_id.lstrip("@")
    if not username or username.startswith("-100"):
        print("[tg_history] Приватный канал — скрейпинг недоступен")
        return set()

    url = "https://t.me/s/" + username
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0 Safari/537.36"
    }

    try:
        print("[tg_history] Скрейплю: " + url)
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code != 200:
            print("[tg_history] HTTP " + str(r.status_code))
            return set()

        soup = BeautifulSoup(r.text, "lxml")
        links = set()

        messages = soup.find_all("div", class_="tgme_widget_message")
        print("[tg_history] Сообщений найдено: " + str(len(messages)))

        for msg in messages[-limit:]:
            for a in msg.find_all("a", href=True):
                href = a["href"]
                if "t.me" in href:
                    continue
                if href.startswith("http"):
                    links.add(href)

        print("[tg_history] Ссылок собрано: " + str(len(links)))
        return links
    except Exception as e:
        print("[tg_history] Ошибка: " + str(e))
        return set()


def merge_history(local_cache, fresh_links):
    merged = set(local_cache)
    merged.update(fresh_links)
    return merged
