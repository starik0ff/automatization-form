FROM python:3.11-slim

# Системные зависимости для Playwright/Chromium на Linux
RUN apt-get update && apt-get install -y \
    wget curl gnupg ca-certificates \
    libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 \
    libgbm1 libasound2 libxrandr2 libxdamage1 libxfixes3 \
    libxcomposite1 libxext6 libx11-6 libxss1 libxtst6 \
    fonts-liberation libappindicator3-1 xdg-utils \
    --no-install-recommends && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Устанавливаем Playwright браузер
RUN playwright install chromium
RUN playwright install-deps chromium

COPY . .

# Директория для сессий
RUN mkdir -p cookies

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
