import json
import re
import google.generativeai as genai

REWRITE_PROMPT = """Ты — автор телеграм-канала "Тут и Там" о путешествиях.
Перепиши статью ниже своими словами, сохранив ВСЕ факты, числа, названия и имена.

Требования:
- Стиль: живо, по-человечески, с лёгкой иронией, но без панибратства.
- Структура: цепляющий заголовок, вводный абзац, 2-4 абзаца основной части, короткий вывод.
- Добавь 1-2 эмодзи по смыслу, не перебарщивай.
- НЕ выдумывай факты, которых нет в исходнике. Если чего-то не хватает — опусти.
- Не используй фразы "в этой статье", "источник сообщает", "как пишет".
- В конце — короткий вопрос читателю.
- Длина: 1200–2000 символов.

Верни СТРОГО JSON без markdown-обёртки:
{"title": "заголовок", "text": "текст статьи", "teaser": "1-2 предложения для превью"}

Исходная статья:
Заголовок: {title}
Текст: {body}
"""


def safe_json_parse(raw: str):
    """Достаёт JSON из ответа модели, даже если он обёрнут в ```json ... ```."""
    if not raw:
        return None
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


def rewrite_article(title: str, body: str, api_key: str, model_name: str = "gemini-2.0-flash"):
    if not api_key:
        return None
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        prompt = REWRITE_PROMPT.format(title=title, body=body[:8000])
        resp = model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
            },
        )
        return safe_json_parse(resp.text)
    except Exception as e:
        print(f"[rewriter] Ошибка Gemini: {e}")
        return None
