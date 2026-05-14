from datetime import datetime

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

TOPICS = [
    {
        "title": "Первая тема",
        "posts": 5,
        "description": "Здесь можно обсудить запуск форума и первые идеи.",
        "tag": "Общее",
    },
    {
        "title": "Вторая тема",
        "posts": 2,
        "description": "Раздел для предложений по улучшению интерфейса и структуры.",
        "tag": "Идеи",
    },
    {
        "title": "Flask и backend",
        "posts": 7,
        "description": "Обсуждение серверной части, маршрутов и API форума.",
        "tag": "Разработка",
    },
]

RULES = [
    "Уважать других участников.",
    "Не публиковать спам.",
    "Писать по теме раздела.",
]

DONATION_CURRENT = 25
DONATION_GOAL = 100


def filter_topics(query: str) -> list[dict]:
    if not query:
        return TOPICS

    normalized_query = query.lower()
    return [
        topic
        for topic in TOPICS
        if normalized_query in topic["title"].lower()
        or normalized_query in topic["description"].lower()
        or normalized_query in topic["tag"].lower()
    ]


@app.get("/")
def index():
    query = request.args.get("q", "").strip()
    topics = filter_topics(query)
    total_posts = sum(topic["posts"] for topic in topics)
    donation_percent = int((DONATION_CURRENT / DONATION_GOAL) * 100)

    return render_template(
        "index.html",
        current_year=datetime.now().year,
        donation_current=DONATION_CURRENT,
        donation_percent=donation_percent,
        donation_goal=DONATION_GOAL,
        query=query,
        rules=RULES,
        topics=topics,
        total_posts=total_posts,
    )


@app.get("/api/topics")
def topics_api():
    query = request.args.get("q", "").strip()
    topics = filter_topics(query)
    return jsonify({"count": len(topics), "items": topics})


if __name__ == "__main__":
    app.run(debug=True)
