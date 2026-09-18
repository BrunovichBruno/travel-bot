import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

print("[posted] === POSTED MANAGER ЗАГРУЖЕН ===")

POSTED_FILE = Path("posted.json")

# Сколько дней хранить историю
RETENTION_DAYS = 90

# Параметры URL, которые считаем мусорными
TRACKING_PARAMS = [
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "yclid", "from", "ref", "referer",
    "_ga", "_gl", "mc_cid", "mc_eid", "igshid", "spm", "share",
]


def normalize_url(url):
    """Приводит URL к каноничному виду: без utm, без якоря, без www, в нижнем регистре."""
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())

        # Убираем www.
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]

        # Убираем трекинг-параметры
        query_pairs = [
            (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=False)
            if k.lower() not in TRACKING_PARAMS
        ]
        new_query = urlencode(query_pairs)

        # Убираем якорь и завершающий слеш
        path = parsed.path.rstrip("/")

        # Собираем обратно
        normalized = urlunparse((
            parsed.scheme.lower(),
            netloc,
            path,
            parsed.params,
            new_query,
            "",  # без fragment
        ))
        return normalized
    except Exception:
        return url.strip().lower()


def load_posted():
    """Загружает историю постов. Поддерживает старый формат (список) и новый (словарь)."""
    if not POSTED_FILE.exists():
        return {}

    try:
        raw = json.loads(POSTED_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print("[posted] Ошибка чтения файла: " + str(e))
        return {}

    # Новый формат: {url: timestamp}
    if isinstance(raw, dict):
        return raw

    # Старый формат: [url, url, ...]
    if isinstance(raw, list):
        now = datetime.now(timezone.utc).isoformat()
        print("[posted] Конвертирую старый формат (" + str(len(raw)) + " записей)")
        return {normalize_url(url): now for url in raw if url}

    return {}


def save_posted(data):
    """Атомарная запись: пишем во временный файл, потом переименовываем."""
    try:
        tmp = POSTED_FILE.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(POSTED_FILE)
        print("[posted] Сохранено записей: " + str(len(data)))
    except Exception as e:
        print("[posted] Ошибка записи: " + str(e))


def is_posted(url, posted):
    """Проверяет, публиковался ли URL."""
    if not url:
        return False
    normalized = normalize_url(url)
    return normalized in posted


def mark_posted(url, posted):
    """Добавляет URL в историю."""
    if not url:
        return
    normalized = normalize_url(url)
    posted[normalized] = datetime.now(timezone.utc).isoformat()


def cleanup_old(posted):
    """Удаляет записи старше RETENTION_DAYS."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    cleaned = {}
    removed = 0
    for url, ts in posted.items():
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt >= cutoff:
                cleaned[url] = ts
            else:
                removed += 1
        except Exception:
            # Битая дата — оставляем
            cleaned[url] = ts
    if removed > 0:
        print("[posted] Очищено старых записей: " + str(removed))
    return cleaned
