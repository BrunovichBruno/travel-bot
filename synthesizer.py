import json
import re
from google import genai

print("[synth] === SYNTHESIZER ЗАГРУЖЕН ===")

SYNTH_PROMPT = """Ты — автор телеграм-канала "Тут и Там" о путешествиях.
Ниже — несколько статей на одну тему из разных источников.

Твоя задача: написать СВОЮ УНИКАЛЬНУЮ статью о путешествиях, объединив информацию из всех источников.

Требования:
- Не пересказывай одну статью — синтезируй факты из всех.
- Если в источниках разные точки зрения — покажи обе.
- Сохрани все числа, цены, названия мест и стран точно.
- НЕ выдумывай факты, которых нет в источниках.
- Стиль: живо, по-человечески, с лёгкой иронией, но без панибратства.
- Структура: цепляющий заголовок, вводный абзац, 3-5 абзацев основной части, короткий вывод.
- Добавь 1-2 эмодзи по смыслу.
- В конце — короткий вопрос читателю.
- Длина: 1500–2500 символов.
- Внутри строк НЕ используй двойные кавычки.

Верни ТОЛЬКО валидный JSON. Первый символ {{, последний }}.
Формат: {{"title": "заголовок", "text": "текст", "teaser": "1-2 предложения"}}

ИСХОДНЫЕ СТАТЬИ:
{articles}
"""


def safe_json_parse(raw):
    if not raw:
        return None
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
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


def synthesize_article(articles_data, api_key, model_name="gemini-3.6-flash"):
    """
    articles_data: список dict с 'title', 'text'.
    Возвращает dict с 'title', 'text', 'teaser'.
    """
    if not api_key or not articles_data:
        return None

    articles_text = ""
    for i, a in enumerate(articles_data, 1):
        articles_text += "\n\n--- Статья " + str(i) + " ---\n"
        articles_text += "Заголовок: " + a.get("title", "") + "\n"
        articles_text += "Текст: " + a.get("text", "")[:4000] + "\n"

    prompt = SYNTH_PROMPT.format(articles=articles_text)

    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        print("[synth] Клиент: " + str(e))
        return None

    from rewriter import FALLBACK_MODELS, try_model

    for m in [model_name] + [x for x in FALLBACK_MODELS if x != model_name]:
        result = try_model(client, m, prompt)
        if result:
            result["style"] = "synthesis"
            return result

    print("[synth] Все модели не сработали")
    return None
