from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
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
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from gemini import GeminiError, generate_support_reply

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
SUPPORT_TOPIC_SLUG = "problems-and-solutions"
SUPPORT_USER_NICKNAME = "Поддержка ALTLINK"
SUPPORT_USER_AVATAR = "altlink icon.png"

DEFAULT_TOPICS = [
    {
        "slug": "problems-and-solutions",
        "title": "Проблемы и решения",
        "description": "Раздел, где можно сообщить о проблемах в работе сервиса и найти помощь.",
        "tag": "Помощь",
    },
    {
        "slug": "service-ideas",
        "title": "Предложения и идеи по улучшению сервиса",
        "description": "Место для идей по развитию ALTLINK, новых функций и улучшения сервера.",
        "tag": "Идеи",
    },
    {
        "slug": "flood",
        "title": "Флуд",
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
    messages = db.relationship("TopicMessage", back_populates="author")

    @property
    def avatar_media_path(self) -> str:
        return self.avatar_filename or get_default_avatar_filename()

    @property
    def gender_label(self) -> str:
        return GENDER_LABELS.get(self.gender, self.gender)


class Topic(db.Model):
    __tablename__ = "topics"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(80), unique=True, nullable=False)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False)
    tag = db.Column(db.String(40), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    messages = db.relationship(
        "TopicMessage",
        back_populates="topic",
        cascade="all, delete-orphan",
        order_by="TopicMessage.created_at.asc()",
    )

    @property
    def message_count(self) -> int:
        return len(self.messages)


class TopicMessage(db.Model):
    __tablename__ = "topic_messages"

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    topic_id = db.Column(db.Integer, db.ForeignKey("topics.id"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    topic = db.relationship("Topic", back_populates="messages")
    author = db.relationship("User", back_populates="messages")


def initialize_storage() -> None:
    MEDIA_ROOT.mkdir(exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def get_default_avatar_filename() -> str:
    for filename in DEFAULT_AVATAR_CANDIDATES:
        if (MEDIA_ROOT / filename).exists():
            return filename
    return DEFAULT_AVATAR_CANDIDATES[0]


def seed_topics() -> None:
    existing_slugs = set(db.session.scalars(db.select(Topic.slug).select_from(Topic)))
    for topic_data in DEFAULT_TOPICS:
        if topic_data["slug"] in existing_slugs:
            continue
        db.session.add(Topic(**topic_data))
    db.session.commit()


def ensure_support_user() -> None:
    support_user = db.session.scalar(
        db.select(User).where(User.nickname == SUPPORT_USER_NICKNAME)
    )
    if support_user is None:
        support_user = User(
            nickname=SUPPORT_USER_NICKNAME,
            password_hash=generate_password_hash(uuid4().hex),
            gender="other",
            avatar_filename=SUPPORT_USER_AVATAR,
        )
        db.session.add(support_user)
        db.session.commit()
        return

    if support_user.avatar_filename != SUPPORT_USER_AVATAR:
        support_user.avatar_filename = SUPPORT_USER_AVATAR
        db.session.commit()


def get_topics(query: str) -> list[Topic]:
    statement = db.select(Topic).options(selectinload(Topic.messages)).order_by(Topic.id.asc())

    if query:
        like_query = f"%{query}%"
        statement = statement.where(
            or_(
                Topic.title.ilike(like_query),
                Topic.description.ilike(like_query),
                Topic.tag.ilike(like_query),
            )
        )

    return list(db.session.scalars(statement).unique())


def get_current_user() -> User | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


def get_recent_users(limit: int = 5) -> list[User]:
    statement = (
        db.select(User)
        .where(User.nickname != SUPPORT_USER_NICKNAME)
        .order_by(User.created_at.desc())
        .limit(limit)
    )
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


def get_topic_by_slug(slug: str) -> Topic | None:
    statement = (
        db.select(Topic)
        .options(selectinload(Topic.messages).selectinload(TopicMessage.author))
        .where(Topic.slug == slug)
    )
    return db.session.scalar(statement)


def get_support_user() -> User:
    support_user = db.session.scalar(
        db.select(User).where(User.nickname == SUPPORT_USER_NICKNAME)
    )
    if support_user is None:
        raise RuntimeError("Пользователь поддержки не инициализирован.")
    return support_user


def publish_support_reply(topic: Topic) -> None:
    if topic.slug != SUPPORT_TOPIC_SLUG or not topic.messages:
        return

    latest_message = topic.messages[-1]
    if latest_message.author.nickname == SUPPORT_USER_NICKNAME:
        return

    reply_text = generate_support_reply(
        topic_title=topic.title,
        topic_description=topic.description,
        messages=[
            {
                "author": message.author.nickname,
                "created_at": message.created_at.strftime("%d.%m.%Y %H:%M"),
                        "content": message.content,
                        "gender": GENDER_LABELS.get(message.author.gender, message.author.gender),
            }
            for message in topic.messages
        ],
    )

    support_user = get_support_user()
    support_message = TopicMessage(
        content=reply_text,
        topic_id=topic.id,
        author_id=support_user.id,
    )
    db.session.add(support_message)
    db.session.commit()


def get_safe_redirect_target(target: str | None) -> str | None:
    if not target:
        return None

    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return None
    if not parts.path.startswith("/"):
        return None
    return target


@app.before_request
def load_current_user() -> None:
    g.current_user = get_current_user()


@app.context_processor
def inject_common_context() -> dict:
    return {
        "current_user": getattr(g, "current_user", None),
        "current_year": datetime.now().year,
        "default_avatar_filename": get_default_avatar_filename(),
        "support_nickname": SUPPORT_USER_NICKNAME,
        "support_topic_slug": SUPPORT_TOPIC_SLUG,
    }


@app.get("/")
def index():
    query = request.args.get("q", "").strip()
    topics = get_topics(query)
    total_posts = sum(topic.message_count for topic in topics)
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


@app.route("/login", methods=["GET", "POST"])
def login():
    errors: list[str] = []
    form_data = {"nickname": ""}
    next_url = get_safe_redirect_target(request.args.get("next"))

    if request.method == "POST":
        nickname = request.form.get("nickname", "").strip()
        password = request.form.get("password", "")
        next_url = get_safe_redirect_target(request.form.get("next"))
        form_data = {"nickname": nickname}

        user = db.session.scalar(db.select(User).where(User.nickname == nickname))

        if user is None or not check_password_hash(user.password_hash, password):
            errors.append("Неверный никнейм или пароль.")
        else:
            session["user_id"] = user.id
            flash("Вход выполнен. Добро пожаловать обратно.", "success")
            return redirect(next_url or url_for("profile_by_nickname", nickname=user.nickname))

    return render_template(
        "login.html",
        errors=errors,
        form_data=form_data,
        next_url=next_url,
    )


@app.get("/profile")
def current_profile():
    if g.current_user is None:
        flash("Сначала войдите в аккаунт, чтобы открыть профиль.", "warning")
        return redirect(url_for("login"))

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


@app.route("/topics/<slug>", methods=["GET", "POST"])
def topic_detail(slug: str):
    topic = get_topic_by_slug(slug)
    if topic is None:
        abort(404)

    errors: list[str] = []
    draft_content = ""

    if request.method == "POST":
        if g.current_user is None:
            flash("Чтобы писать в темах, сначала войдите в аккаунт.", "warning")
            return redirect(url_for("login", next=url_for("topic_detail", slug=topic.slug)))

        draft_content = request.form.get("content", "").strip()

        if not draft_content:
            errors.append("Введите текст сообщения.")
        elif len(draft_content) < 2:
            errors.append("Сообщение должно содержать минимум 2 символа.")
        elif len(draft_content) > 4000:
            errors.append("Сообщение не должно быть длиннее 4000 символов.")

        if not errors:
            message = TopicMessage(
                content=draft_content,
                topic_id=topic.id,
                author_id=g.current_user.id,
            )
            db.session.add(message)
            db.session.commit()

            try:
                refreshed_topic = get_topic_by_slug(topic.slug)
                if refreshed_topic is not None:
                    publish_support_reply(refreshed_topic)
            except GeminiError:
                flash(
                    "Сообщение опубликовано, но Поддержка ALTLINK сейчас не смогла ответить автоматически.",
                    "warning",
                )
            except RuntimeError:
                flash(
                    "Сообщение опубликовано, но служебный аккаунт поддержки не готов к ответу.",
                    "warning",
                )

            flash("Сообщение опубликовано.", "success")
            return redirect(url_for("topic_detail", slug=topic.slug))

    return render_template(
        "topic_detail.html",
        draft_content=draft_content,
        errors=errors,
        topic=topic,
    )


@app.get("/media/<path:filename>")
def media_file(filename: str):
    return send_from_directory(MEDIA_ROOT, filename)


@app.post("/logout")
def logout():
    session.pop("user_id", None)
    flash("Вы вышли из аккаунта.", "success")
    return redirect(url_for("index"))


@app.errorhandler(413)
def file_too_large(_error):
    flash("Аватар слишком большой. Максимальный размер файла: 3 МБ.", "warning")
    return redirect(url_for("register"))


initialize_storage()
with app.app_context():
    db.create_all()
    seed_topics()
    ensure_support_user()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
