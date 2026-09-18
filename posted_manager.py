import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

print("[posted] === POSTED MANAGER v2 ЗАГРУЖЕН ===")

POSTED_FILE = Path("posted.json")
RETENTION_DAYS = 90

TRACKING_PARAMS = [
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "yclid", "from", "ref", "referer",
    "_ga", "_gl", "mc_cid", "mc_eid", "igshid", "spm", "share",
]


def normalize_url(url):
    if not url:
        return ""
    try:
        url = url.strip()
        parsed = urlparse(url)

        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]

        query_pairs = [
            (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=False)
            if k.lower() not in TRACKING_PARAMS
        ]
        new_query = urlencode(query_pairs)

        path = parsed.path.rstrip("/")

        normalized = urlunparse((
            parsed.scheme.lower(),
            netloc,
            path,
            parsed.params,
            new_query,
            "",
        ))
        return normalized
    except Exception:
        return url.strip().lower()


def load_posted():
    """Всегда возвращает dict {url: iso_date}."""
    if not POSTED_FILE.exists():
        return {}

    try:
        raw = json.loads(POSTED_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print("[posted] Ошибка чтения: " + str(e))
        return {}

    if isinstance(raw, dict):
        cleaned = {}
        for k, v in raw.items():
            # Защита от старых мусорных ключей
            if k in ("daily_count", "daily_date", "hashes"):
                continue
            if not k.startswith("http"):
                continue
            cleaned[normalize_url(k)] = v
        return cleaned

    if isinstance(raw, list):
        now = datetime.now(timezone.utc).isoformat()
        return {normalize_url(url): now for url in raw if url and url.startswith("http")}

    return {}


def save_posted(data):
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
    if not url:
        return False
    return normalize_url(url) in posted


def mark_posted(url, posted):
    if not url:
        return
    posted[normalize_url(url)] = datetime.now(timezone.utc).isoformat()


def cleanup_old(posted):
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
            cleaned[url] = ts
    if removed:
        print("[posted] Очищено старых: " + str(removed))
    return cleaned
