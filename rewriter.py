import json
import re
import random
from google import genai

print("[rewriter] === VERSION 8 ЗАГРУЖЕНА (3 стиля + рубрики) ===")

# ==== ПРОМПТЫ ====
PROMPT_NEWS = """Ты — автор телеграм-канала "Тут и Там" о путешествиях.
Перепиши новость ниже своими словами, сохранив ВСЕ факты, числа, названия и имена.

Стиль: живо, по-человечески, с лёгкой иронией, но без панибратства.
Структура: цепляющий заголовок, вводный абзац, 2-4 абзаца основной части, короткий вывод.
Добавь 1-2 эмодзи по смыслу.
НЕ выдумывай факты. Не используй фразы "в этой статье", "источник сообщает".
В конце — короткий вопрос читателю.
Длина: 1200–2000 символов.
Внутри строк НЕ используй двойные кавычки " — заменяй их на «ёлочки» или одинарные '.

Верни ТОЛЬКО валидный JSON, без markdown-обёртки и без пояснений.
Первый символ ответа — {{, последний — }}.
Формат строго такой:
{{"title": "заголовок", "text": "текст статьи", "teaser": "1-2 предложения"}}

Исходная статья:
Заголовок: {title}
Текст: {body}
"""

PROMPT_LIFEHACK = """Ты — автор телеграм-канала "Тут и Там" о путешествиях.
Перепиши материал ниже как ПОЛЕЗНЫЙ ЛАЙФХАК для путешественников.

Стиль: дружелюбно, практично, как совет от опытного друга.
Структура: броский заголовок с обещанием пользы, короткое вступление «почему это важно»,
затем 3-5 конкретных пунктов-советов (каждый с новой строки, без нумерации),
и короткое резюме.
Сохрани все факты, числа, цены, названия из оригинала.
НЕ выдумывай то, чего нет в источнике.
Добавь 1-2 эмодзи.
В конце — вопрос: «А вы так делаете?» или похожий.
Длина: 1200–2000 символов.
Внутри строк НЕ используй двойные кавычки " — заменяй их на «ёлочки» или одинарные '.

Верни ТОЛЬКО валидный JSON, без markdown-обёртки.
Первый символ ответа — {{, последний — }}.
Формат:
{{"title": "заголовок", "text": "текст статьи", "teaser": "1-2 предложения"}}

Исходная статья:
Заголовок: {title}
Текст: {body}
"""

PROMPT_STORY = """Ты — автор телеграм-канала "Тут и Там" о путешествиях.
Перепиши материал ниже как ЖИВУЮ ИСТОРИЮ от третьего лица, с элементами рассказчика.

Стиль: эмоционально, вовлекающе, как будто рассказываешь другу за чашкой кофе.
Структура: интригующий заголовок, завязка, основная часть с деталями, развязка, короткий вывод.
Сохрани все факты, числа, названия и имена из оригинала.
НЕ выдумывай детали, которых нет в источнике.
Добавь 1-2 эмодзи.
В конце — открытый вопрос читателю: «А вы бы так поступили?» или похожий.
Длина: 1200–2000 символов.
Внутри строк НЕ используй двойные кавычки " — заменяй их на «ёлочки» или одинарные '.

Верни ТОЛЬКО валидный JSON, без markdown-обёртки.
Первый символ ответа — {{, последний — }}.
Формат:
{{"title": "заголовок", "text": "текст статьи", "teaser": "1-2 предложения"}}

Исходная статья:
Заголовок: {title}
Текст: {body}
"""

# ==== РУБРИКИ ====
# Ключевые слова → рубрика → хэштеги
RUBRICS = [
    {
        "name": "Визы и документы",
        "keywords": ["виза", "визу", "визов", "внж", "паспорт", "границ", "документ", "миграц"],
        "hashtags": "#ТутИТам #визы #документы #путешествия",
    },
    {
        "name": "Цены и билеты",
        "keywords": ["цена", "цены", "стоимость", "билет", "тариф", "скидк", "распродаж", "дешев", "бюджет", "рубл"],
        "hashtags": "#ТутИТам #цены #билеты #путешествия",
    },
    {
        "name": "Маршруты и направления",
        "keywords": ["маршрут", "направлени", "курорт", "город", "страна", "регион", "отдых", "пляж", "тур"],
        "hashtags": "#ТутИТам #маршруты #кудапоехать #путешествия",
    },
    {
        "name": "Авиа и транспорт",
        "keywords": ["авиакомпан", "рейс", "полет", "полёт", "самолет", "самолёт", "аэропорт", "поезд", "транспорт"],
        "hashtags": "#ТутИТам #авиа #транспорт #путешествия",
    },
    {
        "name": "Отели и проживание",
        "keywords": ["отель", "гостиниц", "хостел", "проживан", "номер", "курорт"],
        "hashtags": "#ТутИТам #отели #проживание #путешествия",
    },
]


def detect_rubric(title, summary, full_text):
    """Определяет рубрику по ключевым словам. Возвращает dict."""
    haystack = (title + " " + summary + " " + full_text[:1500]).lower()
    scores = []
    for rubric in RUBRICS:
        score = sum(1 for kw in rubric["keywords"] if kw in haystack)
        scores.append((score, rubric))
    scores.sort(key=lambda x: x[0], reverse=True)
    if scores and scores[0][0] > 0:
        return scores[0][1]
    # Если ничего не совпало — по умолчанию «Маршруты»
    return RUBRICS[2]


def detect_style(title, summary, full_text):
    """Выбирает стиль промпта: news / lifehack / story."""
    haystack = (title + " " + summary).lower()

    # Лайфхак — если есть слова-маркеры советов
    lifehack_markers = ["совет", "как ", "лайфхак", "способ", "что делать", "инструкц", "правил", "ошибк"]
    if any(m in haystack for m in lifehack_markers):
        return "lifehack", PROMPT_LIFEHACK

    # История — если есть личный опыт, рассказ
    story_markers = ["описал", "рассказал", "поделил", "истори", "опыт", "впечатлен", "туристка", "турист "]
    if any(m in haystack for m in story_markers):
        return "story", PROMPT_STORY

    # Иначе — новость
    return "news", PROMPT_NEWS


FALLBACK_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
]


def safe_json_parse(raw):
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
    try:
        print("[rewriter] Пробую модель: " + model_name)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        raw = response.text if hasattr(response, "text") else str(response)
        print("[rewriter] RAW ответ (первые 600):")
        print(raw[:600])
        print("---END RAW---")
        parsed = safe_json_parse(raw)
        if parsed is None:
            print("[rewriter] JSON не распарсился у " + model_name)
            return None
        print("[rewriter] OK (" + model_name + "), ключи: " + str(list(parsed.keys())))
        return parsed
    except Exception as e:
        print("[rewriter] Ошибка " + model_name + ": " + type(e).__name__ + ": " + str(e))
        return None


def rewrite_article(title, body, api_key, model_name="gemini-3.6-flash", summary=""):
    """
    Рерайт статьи с автоматическим выбором стиля и рубрики.
    Возвращает dict: {title, text, teaser, style, rubric_name, hashtags}
    """
    if not api_key:
        print("[rewriter] Нет GEMINI_API_KEY")
        return None

    style, prompt_template = detect_style(title, summary, body)
    rubric = detect_rubric(title, summary, body)
    print("[rewriter] Стиль: " + style + " | Рубрика: " + rubric["name"])

    prompt = prompt_template.format(title=title, body=body[:8000])

    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        print("[rewriter] Не удалось создать клиент: " + str(e))
        return None

    models_to_try = [model_name] + [m for m in FALLBACK_MODELS if m != model_name]

    for m in models_to_try:
        result = try_model(client, m, prompt)
        if result is not None:
            result["style"] = style
            result["rubric_name"] = rubric["name"]
            result["hashtags"] = rubric["hashtags"]
            return result

    print("[rewriter] Все модели не сработали")
    return None
