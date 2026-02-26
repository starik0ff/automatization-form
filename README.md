# FB Form Bot

Инструмент для массовой автоматической подачи форм на Facebook Support.

## Установка

```bash
cd fb-form-bot
pip install -r requirements.txt
playwright install chromium
```

## Настройка формы

Открой `worker.py` и укажи URL нужной формы:

```python
FORM_URL = "https://www.facebook.com/help/contact/274459462613911"
```

Затем открой DevTools (F12) на странице формы и найди `name` / `id` / `aria-label`
нужных полей. Обнови списки селекторов в методе `run()`.

## Первый запуск — сохранение сессии

```bash
python save_session.py
```

Войди в Facebook вручную в открывшемся браузере, затем нажми Enter в терминале.
Сессия сохранится в `cookies/session.json`.

## Запуск сервера

```bash
uvicorn main:app --reload --port 8000
```

Открой в браузере: http://localhost:8000

## Использование панели

1. Вставь **ссылку на аккаунт** (главное поле формы)
2. Вставь **ссылки на посты** — по одной на строку, или загрузи CSV/TXT файл
3. Нажми **▶ Запустить**
4. Наблюдай за прогрессом в реальном времени

## Формат CSV

Простой список URL, по одному на строке:

```
https://www.facebook.com/post/111111111
https://www.facebook.com/post/222222222
https://www.facebook.com/post/333333333
```

## Структура проекта

```
fb-form-bot/
├── main.py           # FastAPI сервер
├── worker.py         # Playwright автоматизация
├── save_session.py   # Скрипт авторизации
├── requirements.txt
├── cookies/
│   └── session.json  # сохранённая сессия (создаётся автоматически)
└── templates/
    └── index.html    # веб-панель
```
