from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
MEDIA_ROOT = BASE_DIR / "media"
UPLOADS_DIR = MEDIA_ROOT / "uploads"
DATABASE_PATH = BASE_DIR / "forum.db"
DEFAULT_AVATAR_CANDIDATES = [
    "altlink icon.png",
    "logo.png",
    "logo without background.png",
]
ALLOWED_AVATAR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
GENDER_LABELS = {
    "male": "Мужской",
    "female": "Женский",
    "other": "Другой",
}

TOPICS = [
    {
        "title": "Проблемы и решения",
        "posts": 0,
        "description": "Раздел, где можно сообщить о проблемах в работе сервиса и найти помощь.",
        "tag": "Помощь",
    },
    {
        "title": "Предложения и идеи по улучшению сервиса",
        "posts": 0,
        "description": "Место для идей по развитию ALTLINK, новых функций и улучшения сервера.",
        "tag": "Идеи",
    },
    {
        "title": "Флуд",
        "posts": 0,
        "description": "Свободное общение, отзывы и неформальные обсуждения сообщества.",
        "tag": "Общее",
    },
]

RULES = [
    "Уважать других участников.",
    "Не публиковать спам.",
    "Писать по теме раздела.",
]

DONATION_CURRENT = 25
DONATION_GOAL = 100

app = Flask(__name__)
app.config["SECRET_KEY"] = "altlink-forum-dev-secret-key"
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DATABASE_PATH.as_posix()}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 3 * 1024 * 1024

db = SQLAlchemy(app)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    nickname = db.Column(db.String(32), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    gender = db.Column(db.String(20), nullable=False)
    avatar_filename = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def avatar_media_path(self) -> str:
        return self.avatar_filename or get_default_avatar_filename()

    @property
    def gender_label(self) -> str:
        return GENDER_LABELS.get(self.gender, self.gender)


def initialize_storage() -> None:
    MEDIA_ROOT.mkdir(exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def get_default_avatar_filename() -> str:
    for filename in DEFAULT_AVATAR_CANDIDATES:
        if (MEDIA_ROOT / filename).exists():
            return filename
    return DEFAULT_AVATAR_CANDIDATES[0]


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


def get_current_user() -> User | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


def get_recent_users(limit: int = 5) -> list[User]:
    statement = db.select(User).order_by(User.created_at.desc()).limit(limit)
    return list(db.session.scalars(statement))


def save_avatar(file_storage) -> str | None:
    if not file_storage or not file_storage.filename:
        return None

    safe_name = secure_filename(file_storage.filename)
    extension = Path(safe_name).suffix.lower()
    if extension not in ALLOWED_AVATAR_EXTENSIONS:
        allowed = ", ".join(sorted(ext.lstrip(".") for ext in ALLOWED_AVATAR_EXTENSIONS))
        raise ValueError(f"Аватар должен быть в формате: {allowed}.")

    unique_name = f"{uuid4().hex}{extension}"
    destination = UPLOADS_DIR / unique_name
    file_storage.save(destination)
    return f"uploads/{unique_name}"


@app.before_request
def load_current_user() -> None:
    g.current_user = get_current_user()


@app.context_processor
def inject_common_context() -> dict:
    return {
        "current_user": getattr(g, "current_user", None),
        "current_year": datetime.now().year,
        "default_avatar_filename": get_default_avatar_filename(),
    }


@app.get("/")
def index():
    query = request.args.get("q", "").strip()
    topics = filter_topics(query)
    total_posts = sum(topic["posts"] for topic in topics)
    donation_percent = int((DONATION_CURRENT / DONATION_GOAL) * 100)

    return render_template(
        "index.html",
        donation_current=DONATION_CURRENT,
        donation_goal=DONATION_GOAL,
        donation_percent=donation_percent,
        query=query,
        recent_users=get_recent_users(),
        rules=RULES,
        topics=topics,
        total_posts=total_posts,
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    errors: list[str] = []
    form_data = {"nickname": "", "gender": ""}

    if request.method == "POST":
        nickname = request.form.get("nickname", "").strip()
        password = request.form.get("password", "")
        password_repeat = request.form.get("password_repeat", "")
        gender = request.form.get("gender", "")
        avatar = request.files.get("avatar")

        form_data = {"nickname": nickname, "gender": gender}

        if not nickname:
            errors.append("Укажите никнейм.")
        elif len(nickname) < 3:
            errors.append("Никнейм должен содержать минимум 3 символа.")
        elif len(nickname) > 32:
            errors.append("Никнейм не должен быть длиннее 32 символов.")
        elif "/" in nickname or "\\" in nickname:
            errors.append("Никнейм не должен содержать символы / и \\.")
        elif db.session.scalar(db.select(User).where(User.nickname == nickname)):
            errors.append("Пользователь с таким никнеймом уже существует.")

        if not password:
            errors.append("Укажите пароль.")
        elif len(password) < 6:
            errors.append("Пароль должен содержать минимум 6 символов.")

        if password != password_repeat:
            errors.append("Пароли не совпадают.")

        if gender not in GENDER_LABELS:
            errors.append("Выберите пол из списка.")

        avatar_filename = None
        if not errors:
            try:
                avatar_filename = save_avatar(avatar)
            except ValueError as exc:
                errors.append(str(exc))

        if not errors:
            user = User(
                nickname=nickname,
                password_hash=generate_password_hash(password),
                gender=gender,
                avatar_filename=avatar_filename,
            )
            db.session.add(user)
            db.session.commit()
            session["user_id"] = user.id
            flash("Аккаунт создан. Теперь у вас есть собственный профиль.", "success")
            return redirect(url_for("profile_by_nickname", nickname=user.nickname))

    return render_template(
        "register.html",
        errors=errors,
        form_data=form_data,
        gender_labels=GENDER_LABELS,
    )


@app.get("/profile")
def current_profile():
    if g.current_user is None:
        flash("Сначала создайте аккаунт, чтобы открыть профиль.", "warning")
        return redirect(url_for("register"))

    return redirect(url_for("profile_by_nickname", nickname=g.current_user.nickname))


@app.get("/profile/<nickname>")
def profile_by_nickname(nickname: str):
    user = db.session.scalar(db.select(User).where(User.nickname == nickname))
    if user is None:
        abort(404)

    return render_template(
        "profile.html",
        profile_user=user,
    )


@app.get("/media/<path:filename>")
def media_file(filename: str):
    return send_from_directory(MEDIA_ROOT, filename)


@app.errorhandler(413)
def file_too_large(_error):
    flash("Аватар слишком большой. Максимальный размер файла: 3 МБ.", "warning")
    return redirect(url_for("register"))


initialize_storage()
with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True)
