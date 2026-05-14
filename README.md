# Forum ALTLINK

## Запуск

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Локал `http://127.0.0.1:5000`.

## Надёжный запуск на Windows

Если `python app.py` запускается не тем интерпретатором и пишет `No module named 'flask'`, используйте локальное окружение проекта:

```powershell
.\.venv\Scripts\python.exe app.py
```

Или так:

```powershell
.\run.ps1
```

## Что уже есть

- Главная страница форума на `Flask`
- Регистрация аккаунта с `nickname`, паролем, подтверждением пароля, полом и загрузкой аватарки
- Отдельная страница профиля пользователя
- ORM-модель `User` через `Flask-SQLAlchemy`
- Локальная база `SQLite`
- Дефолтная аватарка из папки `media`, если пользователь не загрузил свою
