import json
import random
from datetime import datetime, timezone
from pathlib import Path

print("[poll] === POLL MANAGER ЗАГРУЖЕН ===")

POLL_STATE_FILE = Path("poll_state.json")
MAX_POLLS_PER_DAY = 3
POLL_PROBABILITY = 0.7


def _today_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_poll_state():
    if POLL_STATE_FILE.exists():
        try:
            data = json.loads(POLL_STATE_FILE.read_text(encoding="utf-8"))
            if data.get("date") == _today_utc():
                return data
        except Exception:
            pass
    return {"date": _today_utc(), "count": 0}


def save_poll_state(state):
    try:
        POLL_STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print("[poll] Ошибка записи: " + str(e))


def should_send_poll():
    state = load_poll_state()
    if state["count"] >= MAX_POLLS_PER_DAY:
        print("[poll] Лимит опросов исчерпан: " + str(state["count"]) + "/" + str(MAX_POLLS_PER_DAY))
        return False
    if random.random() > POLL_PROBABILITY:
        print("[poll] Пропуск опроса (случайно)")
        return False
    print("[poll] Опрос будет отправлен: " + str(state["count"] + 1) + "/" + str(MAX_POLLS_PER_DAY))
    return True


def mark_poll_sent():
    state = load_poll_state()
    state["count"] += 1
    save_poll_state(state)
    print("[poll] Счётчик: " + str(state["count"]) + "/" + str(MAX_POLLS_PER_DAY))
