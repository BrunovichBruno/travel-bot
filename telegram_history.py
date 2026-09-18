import json
import requests
from pathlib import Path

print("[tg_history] === TELEGRAM HISTORY ЗАГРУЖЕН ===")

HISTORY_FILE = Path("telegram_history.json")


def load_local_history():
    """Локальный кеш ссылок из Telegram (чтобы не запрашивать каждый раз)."""
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
    """
    Получает последние N сообщений из канала и вытаскивает все ссылки из текста и caption.
    Возвращает set URL-ов.
    """
    if not bot_token or not channel_id:
        return set()

    # Для getHistory нужен chat_id в формате @username или -100...
    # Для публичных каналов работает и @username
    url = "https://api.telegram.org/bot" + bot_token + "/getChatHistory"

    # ВАЖНО: Bot API не имеет прямого getChatHistory.
    # Используем getUpdates — но он видит только свежие апдейты.
    # Поэтому полагаемся на локальный кеш + ручной пересбор при необходимости.
    #
    # Альтернатива: скрейпинг https://t.me/s/<channel> — публичная веб-версия канала.
    # Это надёжнее и не требует прав администратора.

    channel_username = channel_id.lstrip("@")
    if not channel_username or channel_username.startswith("-100"):
        # Приватный канал — не можем скрейпить, возвращаем пусто
        print("[tg_history] Приватный канал, скрейпинг недоступен")
        return set()

    return scrape_channel_links(channel_username, limit=limit)


def scrape_channel_links(channel_username, limit=100):
    """
    Парсит веб-версию канала t.me/s/<username> и вытаскивает ссылки.
    Работает только для публичных каналов.
    """
    from bs4 import BeautifulSoup

    url = "https://t.me/s/" + channel_username
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

        # Собираем все <a href> внутри сообщений
        messages = soup.find_all("div", class_="tgme_widget_message")
        print("[tg_history] Найдено сообщений: " + str(len(messages)))

        for msg in messages[-limit:]:
            for a in msg.find_all("a", href=True):
                href = a["href"]
                # Нас интересуют только внешние ссылки (не t.me)
                if "t.me" in href:
                    continue
                if href.startswith("http"):
                    links.add(href)

        print("[tg_history] Собрано ссылок: " + str(len(links)))
        return links

    except Exception as e:
        print("[tg_history] Ошибка скрейпинга: " + str(e))
        return set()


def merge_history(local_cache, fresh_links):
    """Объединяет локальный кеш и свежие ссылки."""
    merged = set(local_cache)
    merged.update(fresh_links)
    return merged
