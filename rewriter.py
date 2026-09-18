import json
import re
from google import genai

print("[rewriter] === VERSION 7 ЗАГРУЖЕНА (gemini-3.6-flash) ===")

REWRITE_PROMPT = """Ты — автор телеграм-канала "Тут и Там" о путешествиях.
Перепиши статью ниже своими словами, сохранив ВСЕ факты, числа, названия и имена.

Требования к тексту:
- Стиль: живо, по-человечески, с лёгкой иронией, но без панибратства.
- Структура: цепляющий заголовок, вводный абзац, 2-4 абзаца основной части, короткий вывод.
- Добавь 1-2 эмодзи по смыслу, не перебарщивай.
- НЕ выдумывай факты, которых нет в исходнике.
- В конце — короткий вопрос читателю.
- Длина: 1200–2000 символов.
- Внутри строк НЕ используй двойные кавычки " — заменяй их на «ёлочки» или одинарные '.
- Не используй переносы строк внутри значений.

Верни ТОЛЬКО валидный JSON, без markdown-обёртки и без пояснений.
Первый символ ответа — {{, последний — }}.
Формат строго такой:
{{"title": "заголовок", "text": "текст статьи", "teaser": "1-2 предложения для превью"}}

Исходная статья:
Заголовок: {title}
Текст: {body}
"""

# Актуальные модели на 2026 год (согласно документации Google)
FALLBACK_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
]


def safe_json_parse(raw):
    """Достаёт JSON из ответа модели максимально живучим способом."""
    if not raw:
        return None

    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        candidate = match.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            fixed = re.sub(r",\s*}", "}", candidate)
            fixed = re.sub(r",\s*]", "]", fixed)
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass

    return None


def try_model(client, model_name, prompt):
    """Одна попытка рерайта конкретной моделью."""
    try:
        print("[rewriter] Пробую модель: " + model_name)

        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )

        raw = ""
        if hasattr(response, "text"):
            raw = response.text or ""
        else:
            raw = str(response)

        print("[rewriter] RAW ответ (первые 600 символов):")
        print(raw[:600])
        print("---END RAW---")

        parsed = safe_json_parse(raw)
        if parsed is None:
            print("[rewriter] JSON не распарсился у модели " + model_name)
            return None

        print("[rewriter] OK (" + model_name + "), ключи: " + str(list(parsed.keys())))
        return parsed

    except Exception as e:
        print("[rewriter] Ошибка " + model_name + ": " + type(e).__name__ + ": " + str(e))
        return None


def rewrite_article(title, body, api_key, model_name="gemini-3.6-flash"):
    if not api_key:
        print("[rewriter] Нет GEMINI_API_KEY")
        return None

    prompt = REWRITE_PROMPT.format(title=title, body=body[:8000])

    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        print("[rewriter] Не удалось создать клиент: " + str(e))
        return None

    models_to_try = [model_name] + [m for m in FALLBACK_MODELS if m != model_name]

    for m in models_to_try:
        result = try_model(client, m, prompt)
        if result is not None:
            return result

    print("[rewriter] Все модели не сработали")
    return None
