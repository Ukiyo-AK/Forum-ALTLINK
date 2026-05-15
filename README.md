# Forum ALTLINK

## Запуск

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Локал `http://127.0.0.1:5000`.

```powershell
.\.venv\Scripts\python.exe app.py
```

## Что имеется

- Главная страница форума на `Flask`
- Регистрация аккаунта с `nickname`, паролем, подтверждением пароля, полом и загрузкой аватарки
- Отдельная страница профиля пользователя
- ORM-модель `User` через `Flask-SQLAlchemy`
- Темы форума и сообщения пользователей внутри тем
- Локальная база `SQLite`
- Дефолтная аватарка из папки `media`, если пользователь не загрузил свою
- Автоответ Поддержки ALTLINK через `Gemini` в теме `Проблемы и решения`

## Настройка Gemini

В файле `.env` используется переменная:

```env
api_gemini_url=
```

Базовый промтик для нейронки хранится в [gemini_prompt.json]
