from __future__ import annotations

import json
import os
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
PROMPT_FILE = BASE_DIR / "gemini_prompt.json"
API_URL_ENV_KEY = "api_gemini_url"
REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_PROMPT_CONFIG = {
    "system_prompt": (
        "Ты работаешь как Поддержка ALTLINK на форуме сервиса. "
        "Отвечай на русском языке, вежливо, по делу и понятным человеческим тоном. "
        "Помогай пользователю разобраться в проблеме, задавай уточняющие вопросы при необходимости, "
        "не выдумывай факты и не обещай того, чего не можешь проверить. "
        "Если точной причины проблемы не хватает, предложи безопасные шаги диагностики."
    ),
    "max_context_messages": 8,
}


class GeminiError(Exception):
    pass


def load_env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values

    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")

    return values


def get_api_url() -> str:
    return (os.getenv(API_URL_ENV_KEY) or load_env_values().get(API_URL_ENV_KEY, "")).strip()


def load_prompt_config() -> dict:
    if not PROMPT_FILE.exists():
        return DEFAULT_PROMPT_CONFIG.copy()

    try:
        config = json.loads(PROMPT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GeminiError(f"Не удалось прочитать {PROMPT_FILE.name}: {exc}") from exc

    system_prompt = str(config.get("system_prompt") or DEFAULT_PROMPT_CONFIG["system_prompt"]).strip()
    raw_context_limit = config.get("max_context_messages", DEFAULT_PROMPT_CONFIG["max_context_messages"])

    try:
        context_limit = max(1, int(raw_context_limit))
    except (TypeError, ValueError) as exc:
        raise GeminiError("Поле max_context_messages в gemini_prompt.json должно быть числом.") from exc

    return {
        "system_prompt": system_prompt,
        "max_context_messages": context_limit,
    }


def build_prompt(
    topic_title: str,
    topic_description: str,
    messages: list[dict[str, str]],
    last_author_gender: str | None = None,
) -> str:
    config = load_prompt_config()
    recent_messages = messages[-config["max_context_messages"] :]

    conversation = "\n".join(
        f"{message['author']} [{message['created_at']}]: {message['content']}"
        for message in recent_messages
    )

    gender_text = str(last_author_gender).strip() if last_author_gender else "не указан"

    return (
        f"{config['system_prompt']}\n\n"
        f"Название темы: {topic_title}\n"
        f"Описание темы: {topic_description}\n\n"
        f"Последние сообщения в теме:\n{conversation}\n\n"
        f"Пол пользователя, написавшего последнее сообщение: {gender_text}\n\n"
        "Ответь как Поддержка ALTLINK на последнее сообщение пользователя. "
        "Если нужны уточнения, задай их прямо в ответе. "
        "Не используй markdown-заголовки и не упоминай, что ты нейросеть, если это не требуется по смыслу."
    )


def extract_response_text(data: dict) -> str:
    candidates = data.get("candidates")
    if not candidates:
        raise GeminiError(f"API Gemini не вернул candidates: {data}")

    content = candidates[0].get("content", {})
    parts = content.get("parts", [])
    texts = [part.get("text", "").strip() for part in parts if part.get("text")]
    response_text = "\n".join(text for text in texts if text).strip()

    if not response_text:
        raise GeminiError("API Gemini вернул пустой ответ.")

    return response_text


def generate_support_reply(topic_title: str, topic_description: str, messages: list[dict[str, str]]) -> str:
    api_url = get_api_url()
    if not api_url:
        raise GeminiError("URL Gemini API не задан в .env.")

    last_gender = None
    if messages:
        try:
            last_msg = messages[-1]
            if isinstance(last_msg, dict):
                last_gender = last_msg.get("gender") or last_msg.get("sex")
        except Exception:
            last_gender = None

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": build_prompt(
                            topic_title=topic_title,
                            topic_description=topic_description,
                            messages=messages,
                            last_author_gender=last_gender,
                        )
                    }
                ]
            }
        ]
    }

    try:
        response = requests.post(api_url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise GeminiError(f"Не удалось получить ответ от Gemini API: {exc}") from exc
    except ValueError as exc:
        raise GeminiError("Gemini API вернул некорректный JSON.") from exc

    return extract_response_text(data)


if __name__ == "__main__":
    sample_messages = [
        {
            "author": "Пользователь",
            "created_at": "15.05.2026 17:00",
            "content": "После подключения к сервису соединение обрывается каждые 5 минут. Что проверить?",
            "gender": "мужской",
        }
    ]

    try:
        print(generate_support_reply("Проблемы и решения", "Технические вопросы пользователей.", sample_messages))
    except GeminiError as exc:
        print(f"Ошибка Gemini: {exc}")
