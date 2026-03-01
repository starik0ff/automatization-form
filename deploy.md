# Деплой на сервер

## Вариант 1 — Docker (рекомендуется)

```bash
# На сервере (Ubuntu/Debian)
git clone https://github.com/intersson-sir/automatization-form.git
cd automatization-form

docker build -t fb-bot .
docker run -d \
  --name fb-bot \
  -p 8000:8000 \
  -v $(pwd)/cookies:/app/cookies \
  -v $(pwd)/stats.json:/app/stats.json \
  fb-bot
```

Открываешь панель: `http://IP_СЕРВЕРА:8000`  
Переходишь **FB Сессия** → вводишь email/пароль Facebook → жмёшь **Войти**.  
Сессия сохраняется в `cookies/session.json` (volume смонтирован, не исчезнет при рестарте).

---

## Вариант 2 — Без Docker (вручную)

```bash
# Устанавливаем зависимости системы (Ubuntu)
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv wget curl

# Клонируем проект
git clone https://github.com/intersson-sir/automatization-form.git
cd automatization-form

# Виртуальное окружение
python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium

# Запуск
uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## Войти в Facebook (headless на сервере)

1. Открой `http://IP:8000` в браузере
2. Клик **🔐 FB Сессия** в сайдбаре
3. Введи email и пароль от Facebook
4. Нажми **Войти и сохранить сессию**

> Если Facebook просит 2FA — войди вручную на Mac, скопируй `cookies/session.json` на сервер:
> ```bash
> scp cookies/session.json user@IP:/path/to/app/cookies/session.json
> ```

---

## Автозапуск (systemd)

```ini
# /etc/systemd/system/fb-bot.service
[Unit]
Description=FB Form Bot
After=network.target

[Service]
WorkingDirectory=/path/to/automatization-form
ExecStart=/path/to/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
User=ubuntu

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable fb-bot
sudo systemctl start fb-bot
```
