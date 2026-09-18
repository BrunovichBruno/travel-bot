import os
import json
import random
import time
from pathlib import Path

import feedparser
import requests
from google import genai

from extractor import extract_full_text, extract_image
from rewriter import rewrite_article
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

print("[bot] === BOT VERSION 12 ЗАГРУЖЕНА ===")

RSS_FEEDS = [
    "https://lenta.ru/rss/news/travel",
    "https://lenta.ru/rss/articles/travel",
    "https://ria.ru/export/rss2/index.xml",
    "https://www.tourprom.ru/rss/",
    "https://www.rbc.ru/rss/travel",
    "https://tass.ru/rss/v2.xml",
    "https://www.atorus.ru/rss/news.xml",
    "https://www.interfax.ru/rss.asp",
]

KEYWORDS = ["туризм", "путешеств", "тур", "отдых", "виза", "авиа",
            "отель", "курорт", "билет", "авиакомпания", "рейс",
            "направление", "страна", "город", "пляж", "экскурсия"]

BLOCKED_WORDS = ["убил", "убийств", "погиб", "погибл", "смерть", "умер",
                 "утопул", "утопленник", "изнасил", "ограбил", "ограблени",
                 "задержан", "арестован", "осужден", "тюрьм", "наркотик",
                 "криминал", "происшеств", "катастроф", "крушени", "авари",
                 "теракт", "дтп", "пожар", "утону", "зарезал", "застрелил",
                 "избил", "избиени", "насили", "домогательств", "разврат"]

MAX_POSTS_PER_RUN = 3
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
MIN_TEXT_LENGTH = 500
MAX_TEXT_LENGTH = 15000
DELAY_MIN = 600
DELAY_MAX = 1200
WIKI_PROBABILITY = 0.3

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
G
