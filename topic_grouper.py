import re

print("[grouper] === TOPIC GROUPER ЗАГРУЖЕН ===")

STOP_WORDS = {
    "и", "в", "на", "с", "по", "для", "от", "до", "к", "о",
    "что", "как", "это", "не", "но", "а", "или", "же", "бы",
    "россия", "россии", "россиян", "российский", "год", "года",
    "стал", "стала", "будет", "было", "есть", "может", "могут",
    "также", "уже", "ещё", "еще", "все", "всё", "весь", "вся",
    "который", "которая", "которые", "чтобы", "если", "когда",
}


def extract_keywords(title):
    """Извлекает ключевые слова из заголовка."""
    words = re.findall(r"[а-яёa-z]{4,}", title.lower())
    return set(w for w in words if w not in STOP_WORDS)


def group_by_topic(articles, min_group_size=3):
    """
    Группирует статьи по теме.
    articles: список dict с 'title', 'link', 'summary'.
    Возвращает список групп.
    """
    groups = []
    used = set()

    for i, a1 in enumerate(articles):
        if i in used:
            continue
        kw1 = extract_keywords(a1["title"])
        if not kw1:
            continue

        group = [a1]
        group_kw = set(kw1)

        for j, a2 in enumerate(articles):
            if j <= i or j in used:
                continue
            kw2 = extract_keywords(a2["title"])
            if len(group_kw & kw2) >= 2:
                group.append(a2)
                group_kw |= kw2
                used.add(j)

        if len(group) >= min_group_size:
            groups.append(group)
            used.add(i)

    print("[grouper] Найдено групп: " + str(len(groups)))
    for g in groups:
        print("[grouper] Группа: " + g[0]["title"][:60] + " (+" + str(len(g) - 1) + " статей)")

    return groups
