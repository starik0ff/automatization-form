"""
Headless-логин в Facebook и сохранение сессии.
Работает без экрана — подходит для сервера.
"""

import platform
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

SESSION_PATH = Path(__file__).parent / "cookies" / "session.json"
IS_HEADLESS  = platform.system() == "Linux"


def login_and_save(fb_email: str, fb_password: str) -> tuple:
    """
    Логинится в Facebook headless и сохраняет сессию.
    Возвращает (True, "OK") или (False, "сообщение об ошибке").
    """
    SESSION_PATH.parent.mkdir(exist_ok=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=IS_HEADLESS,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/121.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()

            # Открываем страницу логина
            page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_load_state("networkidle", timeout=15000)

            # Принимаем куки если есть попап
            try:
                cookie_btn = page.get_by_role("button", name="Allow all cookies")
                if cookie_btn.is_visible(timeout=3000):
                    cookie_btn.click()
                    time.sleep(1)
            except Exception:
                pass
            try:
                cookie_btn2 = page.get_by_role("button", name="Accept all")
                if cookie_btn2.is_visible(timeout=2000):
                    cookie_btn2.click()
                    time.sleep(1)
            except Exception:
                pass

            # Вводим email
            email_field = page.locator("#email")
            email_field.wait_for(timeout=10000)
            email_field.fill(fb_email)
            time.sleep(0.5)

            # Вводим пароль
            page.locator("#pass").fill(fb_password)
            time.sleep(0.5)

            # Нажимаем Login
            page.locator("[name='login']").click()

            # Ждём результата (редирект или ошибка)
            time.sleep(4)

            current_url = page.url

            # Проверяем на ошибку логина
            if "login" in current_url and "checkpoint" not in current_url:
                error_el = page.locator("#error_box, [data-testid='royal_login_form'] div[role='alert']")
                if error_el.count() > 0:
                    err_text = error_el.first.inner_text()
                    browser.close()
                    return False, f"Ошибка Facebook: {err_text[:200]}"

            # Проверяем на двухфакторку / checkpoint
            if "checkpoint" in current_url or "two_step" in current_url:
                browser.close()
                return False, "Facebook требует подтверждение (2FA/checkpoint). Войди вручную на Mac и загрузи session.json на сервер."

            # Проверяем что вошли успешно
            if "facebook.com" in current_url and "login" not in current_url:
                context.storage_state(path=str(SESSION_PATH))
                browser.close()
                return True, "Сессия сохранена успешно"

            # Дополнительное ожидание если ещё грузится
            time.sleep(3)
            context.storage_state(path=str(SESSION_PATH))
            browser.close()
            return True, "Сессия сохранена"

    except PlaywrightTimeout:
        return False, "Таймаут при загрузке Facebook"
    except Exception as e:
        return False, str(e)
