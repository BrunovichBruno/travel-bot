import json
import re
from google import genai

print("[rewriter] === REWRITER v7 (много рубрик) ЗАГРУЖЕН ===")

PROMPT_NEWS = """Ты — автор телеграм-канала "Тут и Там" о путешествиях.
Перепиши новость ниже своими словами, сохранив ВСЕ факты, числа, названия и имена.

Стиль: живо, с лёгкой иронией, но без панибратства.
Структура: цепляющий заголовок, вводный абзац, 2-4 абзаца, короткий вывод.
Добавь 1-2 эмодзи.
В конце — короткий вопрос читателю.
Длина: 1200–2000 символов.
Внутри строк НЕ используй двойные кавычки.

Верни ТОЛЬКО валидный JSON. Первый символ {{, последний }}.
Формат: {{"title": "заголовок", "text": "текст", "teaser": "1-2 предложения"}}

Заголовок: {title}
Текст: {body}
"""

PROMPT_LIFEHACK = """Ты — автор телеграм-канала "Тут и Там" о путешествиях.
Перепиши материал ниже как ПОЛЕЗНЫЙ ЛАЙФХАК для путешественников.

Стиль: дружелюбно, практично.
Структура: броский заголовок, короткое вступление, 3-5 пунктов-советов, резюме.
Добавь 1-2 эмодзи.
В конце — вопрос «А вы так делаете?».
Длина: 1200–2000 символов.
Внутри строк НЕ используй двойные кавычки.

Верни ТОЛЬКО валидный JSON. Первый символ {{, последний }}.
Формат: {{"title": "заголовок", "text": "текст", "teaser": "1-2 предложения"}}

Заголовок: {title}
Текст: {body}
"""

PROMPT_STORY = """Ты — автор телеграм-канала "Тут и Там" о путешествиях.
Перепиши материал ниже как ЖИВУЮ ИСТОРИЮ от третьего лица.

Стиль: эмоционально, вовлекающе.
Структура: интригующий заголовок, завязка, детали, развязка.
Добавь 1-2 эмодзи.
В конце — открытый вопрос.
Длина: 1200–2000 символов.
Внутри строк НЕ используй двойные кавычки.

Верни ТОЛЬКО валидный JSON. Первый символ {{, последний }}.
Формат: {{"title": "заголовок", "text": "текст", "teaser": "1-2 предложения"}}

Заголовок: {title}
Текст: {body}
"""

# 17 рубрик — тревел-журнал (без дублирования ключевых слов)
RUBRICS = [
    {"name": "Кухня и блюда",
     "keywords": ["кухн", "блюд", "ресторан", "гастроном", "десерт", "сыр", "вино", "кофе"],
     "hashtags": "#ТутИТам #еда #кухня #гастрономия"},
    {"name": "Напитки",
     "keywords": ["напитк", "вино", "пиво", "коктейл", "чай", "кофе"],
     "hashtags": "#ТутИТам #напитки #вино #кофе"},
    {"name": "Достопримечательности",
     "keywords": ["достопримечательн", "музей", "храм", "собор", "замок", "крепост", "памятник"],
     "hashtags": "#ТутИТам #достопримечательности #туризм"},
    {"name": "Города и регионы",
     "keywords": ["город", "столиц", "регион", "город-миллионер"],
     "hashtags": "#ТутИТам #города #кудапоехать"},
    {"name": "Курорты",
     "keywords": ["курорт", "санатор", "спа", "термальн"],
     "hashtags": "#ТутИТам #курорты #отдых"},
    {"name": "Природа и парки",
     "keywords": ["парк", "заповедник", "природа", "лес", "джунгл"],
     "hashtags": "#ТутИТам #природа #парки"},
    {"name": "Горы и водопады",
     "keywords": ["гор", "водопад", "вулкан", "скал", "вершин", "альп"],
     "hashtags": "#ТутИТам #горы #водопады #походы"},
    {"name": "Озёра и реки",
     "keywords": ["озер", "рек", "водохранилищ", "канал"],
     "hashtags": "#ТутИТам #озёра #реки #природа"},
    {"name": "Пляжи и острова",
     "keywords": ["пляж", "остров", "море", "океан", "лагуна", "бухт"],
     "hashtags": "#ТутИТам #пляжи #острова #отдых"},
    {"name": "Культура и традиции",
     "keywords": ["традиц", "культур", "обыча", "символ", "народн"],
     "hashtags": "#ТутИТам #традиции #культура"},
    {"name": "Праздники и фестивали",
     "keywords": ["праздник", "фестивал", "карнавал", "парад"],
     "hashtags": "#ТутИТам #праздники #фестивали"},
    {"name": "История и легенды",
     "keywords": ["истори", "легенд", "миф", "древн", "средневеков"],
     "hashtags": "#ТутИТам #история #легенды"},
    {"name": "Визы и документы",
     "keywords": ["виза", "визов", "паспорт", "границ", "миграц"],
     "hashtags": "#ТутИТам #визы #документы #граница"},
    {"name": "Авиа и транспорт",
     "keywords": ["авиакомпан", "рейс", "самолет", "аэропорт", "поезд", "транспорт"],
     "hashtags": "#ТутИТам #авиа #транспорт #билеты"},
    {"name": "Отели и проживание",
     "keywords": ["отель", "гостиниц", "хостел", "проживан", "кемпинг", "номер"],
     "hashtags": "#ТутИТам #отели #проживание"},
    {"name": "Лайфхаки в поездках",
     "keywords": ["лайфхак", "совет", "как ", "способ", "инструкц", "ошибк"],
     "hashtags": "#ТутИТам #лайфхаки #советы"},
    {"name": "Интересные факты",
     "keywords": ["факт", "интересн", "удивительн", "необычн"],
     "hashtags": "#ТутИТам #факты #интересное"},
]

FALLBACK_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
]


def detect_rubric(title, summary, full_text):
    haystack = (title + " " + summary + " " + full_text[:1500]).lower()
    scores = [(sum(1 for kw in r["keywords"] if kw in haystack), r) for r in RUBRICS]
    scores.sort(key=lambda x: x[0], reverse=True)
    if scores and scores[0][0] > 0:
        return scores[0][1]
    return RUBRICS[16]  # Интересные факты как fallback


def detect_style(title, summary, full_text):
    haystack = (title + " " + summary).lower()
    if any(m in haystack for m in ["совет", "как ", "лайфхак", "способ", "инструкц", "ошибк"]):
        return "lifehack", PROMPT_LIFEHACK
    if any(m in haystack for m in ["описал", "рассказал", "поделил", "истори", "опыт"]):
        return "story", PROMPT_STORY
    return "news", PROMPT_NEWS


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


def try_model(client, model_name, prompt):
    try:
        print("[rewriter] Пробую: " + model_name)
        response = client.models.generate_content(model=model_name, contents=prompt)
        raw = response.text if hasattr(response, "text") else str(response)
        print("[rewriter] RAW (600):\n" + raw[:600] + "\n---END---")
        parsed = safe_json_parse(raw)
        if parsed:
            print("[rewriter] OK: " + str(list(parsed.keys())))
        return parsed
    except Exception as e:
        print("[rewriter] " + model_name + ": " + type(e).__name__ + ": " + str(e))
        return None


def rewrite_article(title, body, api_key, model_name="gemini-3.6-flash", summary=""):
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
        print("[rewriter] Клиент: " + str(e))
        return None

    for m in [model_name] + [x for x in FALLBACK_MODELS if x != model_name]:
        result = try_model(client, m, prompt)
        if result:
            result["style"] = style
            result["rubric_name"] = rubric["name"]
            result["hashtags"] = rubric["hashtags"]
            return result
    return None
