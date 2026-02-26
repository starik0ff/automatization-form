"""
Запусти этот скрипт ОДИН РАЗ чтобы войти в Facebook вручную.
Сессия сохранится в cookies/session.json и будет использоваться ботом.

Запуск:
    python save_session.py
"""

from pathlib import Path
from playwright.sync_api import sync_playwright

SESSION_PATH = Path("cookies/session.json")


def main():
    SESSION_PATH.parent.mkdir(exist_ok=True)

    print("=" * 50)
    print("Открываю браузер. Войди в Facebook вручную.")
    print("После входа нажми Enter в этом терминале.")
    print("=" * 50)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.goto("https://www.facebook.com/login")

        input("\n✅ Войди в аккаунт в браузере, затем нажми Enter здесь...\n")

        context.storage_state(path=str(SESSION_PATH))
        browser.close()

    print(f"✅ Сессия сохранена в {SESSION_PATH}")
    print("Теперь можно запускать бота: uvicorn main:app --reload")


if __name__ == "__main__":
    main()
