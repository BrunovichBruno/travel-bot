import os
import html
from telegraph import Telegraph

print("[telegraph] === TELEGRAPH PUBLISHER ЗАГРУЖЕН ===")


def publish_to_telegraph(title, text, source_url, author="Тут и Там"):
    token = os.getenv("TELEGRAPH_TOKEN")

    try:
        if token:
            tg = Telegraph(access_token=token)
        else:
            tg = Telegraph()
            tg.create_account(short_name="tutitam", author_name=author)

        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        content = "".join("<p>" + html.escape(p) + "</p>" for p in paragraphs)
        content += '<p><i>Источник: <a href="' + source_url + '">оригинал</a></i></p>'

        response = tg.create_page(title=title, author_name=author, html_content=content)
        return "https://telegra.ph/" + response["path"]
    except Exception as e:
        print("[telegraph] Ошибка: " + str(e))
        return None
