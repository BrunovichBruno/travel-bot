import json
import re
import google.generativeai as genai

print("[rewriter] === VERSION 4 ЗАГРУЖЕНА ===")

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


def rewrite_article(title, body, api_key, model_name="gemini-3.6-flash"):
    if not api_key:
        print("[rewriter] Нет GEMINI_API_KEY")
        return None

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        prompt = REWRITE_PROMPT.format(title=title, body=body[:8000])

        print("[rewriter] Отправляю в Gemini (" + model_name + "), длина промпта: " + str(len(prompt)))

        resp = model.generate_content(prompt)

        raw = ""
        if hasattr(resp, "text"):
            raw = resp.text or ""
        else:
            raw = str(resp)

        print("[rewriter] RAW ответ (первые 600 символов):")
        print(raw[:600])
        print("---END RAW---")

        parsed = safe_json_parse(raw)
        if parsed is None:
            print("[rewriter] JSON не распарсился")
        else:
            print("[rewriter] OK, ключи: " + str(list(parsed.keys())))
        return parsed

    except Exception as e:
        print("[rewriter] Ошибка Gemini: " + type(e).__name__ + ": " + str(e))
        return None
