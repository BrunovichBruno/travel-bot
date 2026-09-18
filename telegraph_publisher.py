import os
from telegraph import Telegraph


def publish_to_telegraph(title: str, text: str, source_url: str, author: str = "Тут и Там"):
    """Публикует статью в Telegraph и возвращает ссылку."""
    token = os.getenv("TELEGRAPH_TOKEN")

    try:
        if token:
            tg = Telegraph(access_token=token)
        else:
            tg = Telegraph()
            tg.create_account(short_name="tutitam", author_name=author)

        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        content = "".join(f"<p>{p}</p>" for p in paragraphs)
        content += f'<p><i>Источник: <a href="{source_url}">оригинал</a></i></p>'

        response = tg.create_page(
            title=title,
            author_name=author,
            html_content=content,
        )
        return f"https://telegra.ph/{response['path']}"
    except Exception as e:
        print(f"[telegraph] Ошибка: {e}")
        return None
