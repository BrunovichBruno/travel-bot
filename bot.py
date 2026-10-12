import os
import json
import random
import time
from pathlib import Path

import feedparser
import requests
from google import genai

from extractor import extract_full_text, extract_image
from rewriter import rewrite_article, detect_rubric
from telegraph_publisher import publish_to_telegraph
from poll_manager import should_send_poll, mark_poll_sent, load_poll_state
from wikipedia_source import get_random_wiki_article
from wiki_prompts import get_prompt_for_rubric, get_hashtags_for_rubric
from posted_manager import (
    load_posted, save_posted, is_posted, mark_posted,
    cleanup_old, normalize_url,
)
from telegram_history import (
    load_local_history, save_local_history,
    fetch_telegram_links, merge_history,
)

print("[bot] === BOT VERSION 14 (Тут и Там, синтез) ЗАГРУЖЕНА ===")

RSS_FEEDS = [
    "https://lenta.ru/rss/news/travel",
    "https://lenta.ru/rss/articles/travel",
    "https://ria.ru/export/rss2/index.xml",
    "https://tass.ru/rss/v2.xml",
    "https://www.interfax.ru/rss.asp",
    "https://www.tourprom.ru/rss/",
    "https://www.atorus.ru/rss/news.xml",
    "https://www.travel.ru/rss/",
    "https://www.vesti.ru/rss/travel.xml",
    "https://www.vedomosti.ru/rss/news",
    "https://1prime.ru/export/rss2/index.xml",
]

KEYWORDS = [
    "туризм", "путешеств", "тур", "отдых", "виза", "авиа",
    "отель", "курорт", "билет", "авиакомпания", "рейс",
    "направление", "страна", "город", "пляж", "экскурсия",
    "достопримечательн", "маршрут", "поездк", "отпуск",
    "кухн", "блюд", "ресторан", "отдыхающ", "гостиниц",
    "хостел", "кемпинг", "туроператор", "путевк", "круиз",
]

BLOCKED_WORDS = [
    # Криминал
    "убил", "убийств", "погиб", "погибл", "смерть", "умер",
    "утопул", "утопленник", "изнасил", "ограбил", "ограблени",
    "задержан", "арестован", "осужден", "тюрьм", "наркотик",
    "криминал", "происшеств", "катастроф", "крушени", "авари",
    "теракт", "дтп", "пожар", "утону", "зарезал", "застрелил",
    "избил", "избиени", "насили", "домогательств", "разврат",
    "укусил", "напал", "драк", "жестоко",
    # Политика
    "путин", "кремл", "спецоперац", "военн", "арми", "оружи",
    "беспилотник", "дрон", "аэс", "конфликт", "обстрел",
    "мобилизац", "минобороны", "генштаб", "нато", "трамп",
    "байден", "зеленск", "украин", "националист",
    # Шоу-бизнес
    "долин", "артист", "певиц", "актер", "звезд", "селебрит",
    # Не по теме
    "хоккеист", "футболист", "олимпиад", "чемпионат",
]

MAX_POSTS_PER_RUN = 4
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
MIN_TEXT_LENGTH = 500
MAX_TEXT_LENGTH = 15000
DELAY_MIN = 180
DELAY_MAX = 300

WIKI_PROBABILITY = 0.25
SYNTH_PROBABILITY = 0.35

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

IMAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


def matches_keywords(text):
    return any(kw in text.lower() for kw in KEYWORDS)


def has_blocked_words(text):
    return any(bad in text.lower() for bad in BLOCKED_WORDS)


POLLS = {
    "Визы и документы": {"question": "Сталкивались с этим?",
        "options": ["Да", "Нет", "Планирую", "Не актуально"]},
    "Цены и билеты": {"question": "Готовы платить?",
        "options": ["Да", "Дорого", "Дёшево", "Не поеду"]},
    "Маршруты и направления": {"question": "Поехали бы сюда?",
        "options": ["Хочу! 🔥", "Подумаю", "Не моё", "Уже был(а)"]},
    "Авиа и транспорт": {"question": "Как предпочитаете?",
        "options": ["Самолёт", "Поезд", "Авто
