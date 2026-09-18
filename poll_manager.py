import json
import random
from datetime import datetime, timezone
from pathlib import Path

POLL_STATE_FILE = Path("poll_state.json")

# Сколько опросов максимум в сутки
MAX_POLLS_PER_DAY = 3

# Шанс, что пост получит опрос (если лимит ещё не исчерпан)
# 0.5 = примерно половина постов из оставшихся слотов получат опрос
POLL_PROBABILITY = 0.7


def _today_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_poll_state():
    """Загружает состояние: {'date': '2026-09-18', 'count': 2}."""
    if POLL_STATE_FILE.exists():
        try:
            data = json.loads(POLL_STATE_FILE.read_text(encoding="utf-8"))
            if data.get("date") == _today_utc():
                return data
        except Exception:
            pass
    # Новый день или файла нет — обнуляем
    return {"date": _today_utc(), "count": 0}


def save_poll_state(state):
    POLL_STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def should_send_poll():
    """
    Решает, отправлять ли опрос к текущему посту.
    Учитывает дневной лимит и случайность.
    Возвращает True/False.
    """
    state = load_poll_state()

    if state["count"] >= MAX_POLLS_PER_DAY:
        print("[poll] Дневной лимит опросов исчерпан (" + str(state["count"]) + "/" + str(MAX_POLLS_PER_DAY) + ")")
        return False

    # Случайность: не каждый пост получает опрос
    if random.random() > POLL_PROBABILITY:
        print("[poll] Пропускаю опрос для этого поста (случайно)")
        return False

    print("[poll] Опрос будет отправлен (" + str(state["count"] + 1) + "/" + str(MAX_POLLS_PER_DAY) + " за сегодня)")
    return True


def mark_poll_sent():
    """Увеличивает счётчик опросов за сегодня."""
    state = load_poll_state()
    state["count"] += 1
    save_poll_state(state)
    print("[poll] Счётчик обновлён: " + str(state["count"]) + "/" + str(MAX_POLLS_PER_DAY))
