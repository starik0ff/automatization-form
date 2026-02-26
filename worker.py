import json
import random
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

FORM_URL = "https://www.facebook.com/help/contact/1758255661104383"

LINKS_PER_BATCH = 30
DELAY_MIN = 8
DELAY_MAX = 18


class BotWorker:
    def __init__(self, account_url: str, post_urls: list[str], static: dict,
                 status_file: Path, on_finish=None):
        self.account_url = account_url
        self.post_urls = post_urls
        self.static = static
        self.status_file = status_file
        self.on_finish = on_finish
        self._stop = False
        self.batches = [
            post_urls[i:i + LINKS_PER_BATCH]
            for i in range(0, len(post_urls), LINKS_PER_BATCH)
        ]

    def stop(self):
        self._stop = True

    def _save(self, state: str, done: int, failed: int, log: list[str]):
        with open(self.status_file, "w") as f:
            json.dump({
                "state": state,
                "total": len(self.post_urls),
                "done": done,
                "failed": failed,
                "log": log[-100:],
            }, f, ensure_ascii=False)

    def run(self):
        log = [f"Постов: {len(self.post_urls)}, батчей: {len(self.batches)} (по {LINKS_PER_BATCH})"]
        done = failed = 0

        session_path = Path("cookies/session.json")
        if not session_path.exists():
            log.append("⚠️  Сессия не найдена. Запусти save_session.py")
            self._save("error", done, failed, log)
            return

        self._save("running", done, failed, log)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                context = browser.new_context(
                    storage_state=str(session_path),
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/121.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 900},
                )
                page = context.new_page()

                for i, batch in enumerate(self.batches):
                    if self._stop:
                        log.append("⛔ Остановлено пользователем.")
                        break

                    log.append(f"📋 Батч {i+1}/{len(self.batches)} — {len(batch)} ссылок...")
                    self._save("running", done, failed, log)

                    try:
                        ok = self._submit_batch(page, batch, log)
                        if ok:
                            done += len(batch)
                            log.append(f"✅ Батч {i+1} отправлен ({len(batch)} постов)")
                        else:
                            failed += len(batch)
                            log.append(f"❌ Батч {i+1} не удался")
                    except PlaywrightTimeout:
                        failed += len(batch)
                        log.append(f"⏱ Батч {i+1}: таймаут")
                    except Exception as e:
                        failed += len(batch)
                        log.append(f"❌ Батч {i+1}: {str(e)[:150]}")

                    self._save("running", done, failed, log)

                    if i < len(self.batches) - 1 and not self._stop:
                        delay = random.uniform(DELAY_MIN, DELAY_MAX)
                        log.append(f"⏳ Пауза {delay:.1f}с...")
                        self._save("running", done, failed, log)
                        time.sleep(delay)

                context.close()
                browser.close()

        except Exception as e:
            log.append(f"💥 Критическая ошибка: {str(e)}")
            self._save("error", done, failed, log)
            return

        state = "stopped" if self._stop else "done"
        log.append(f"🏁 Готово. Отправлено: {done}, ошибок: {failed}")
        self._save(state, done, failed, log)
        if self.on_finish:
            try:
                self.on_finish(done, failed, len(self.batches))
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────
    def _submit_batch(self, page, batch: list[str], log: list[str]) -> bool:
        s = self.static

        page.goto(FORM_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)

        # 1. I am the rights owner
        self._click_any(page, [
            "label:has-text('I am the rights owner')",
            "input[type='radio']:first-of-type",
        ])
        self._pause()

        # 2. Full name
        self._fill(page, [
            "input[name='full_name']",
            "input[placeholder*='full name']",
            "input[placeholder*='name']",
        ], s["full_name"])

        # 3. Email
        self._fill(page, [
            "input[name='email']",
            "input[type='email']",
            "input[placeholder*='email']",
        ], s["email"])

        # 4. Confirm email
        self._fill(page, [
            "input[name='confirm_email']",
            "input[placeholder*='onfirm']",
        ], s["email"])

        self._pause()

        # 5. Country
        try:
            page.locator("select").first.select_option(label=s["country"])
        except Exception:
            pass

        # 6. Work type — может быть несколько через ", "
        for wt in [w.strip() for w in s["work_type"].split(",") if w.strip()]:
            self._click_any(page, [
                f"label:has-text('{wt}')",
                f"input[value='{wt.lower()}']",
            ])
            time.sleep(random.uniform(0.2, 0.5))
        self._pause()

        # 7. Rights owner name
        self._fill(page, [
            "input[name='rights_owner']",
            "input[placeholder*='rights owner']",
            "input[placeholder*='organization']",
            "input[placeholder*='Name of']",
        ], s["rights_owner_name"])

        # 8. Link to copyrighted work (account / original)
        self._fill(page, [
            "input[name='original_url']",
            "input[placeholder*='link to']",
            "input[placeholder*='your website']",
            "input[placeholder*='copyrighted']",
        ], self.account_url)

        # 9. Describe copyrighted work
        self._fill(page, [
            "textarea[name='work_description']",
            "textarea:nth-of-type(1)",
        ], s["work_description"])

        self._pause()

        # 10. Content type = Photo, video or post
        self._click_any(page, [
            "label:has-text('Photo, video or post')",
            "label:has-text('Photo')",
        ])
        self._pause()

        # 11. Post links (Link 1 … Link N)
        for idx, url in enumerate(batch):
            # Начиная со второй ссылки — нужно открыть дополнительные поля
            if idx == 10:
                self._click_any(page, [
                    "a:has-text('additional links')",
                    "span:has-text('additional links')",
                    "*:has-text('I have additional links')",
                ])
                time.sleep(0.5)

            field_n = idx + 1
            filled = False
            for sel in [
                f"input[aria-label='Link {field_n}']",
                f"input[placeholder='Link {field_n}']",
                f"input[name='url_{field_n}']",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.count() > 0 and el.is_visible(timeout=1500):
                        el.scroll_into_view_if_needed()
                        el.fill("")
                        el.type(url, delay=random.randint(20, 50))
                        filled = True
                        break
                except Exception:
                    continue

            if not filled:
                # Fallback: все input-поля связанные с url на странице
                try:
                    inputs = page.locator("input[type='text'], input[type='url']")
                    # Пропускаем первые поля (имя, email, etc.) — берём начиная с ~6-го
                    el = inputs.nth(5 + idx)
                    el.scroll_into_view_if_needed()
                    el.fill("")
                    el.type(url, delay=random.randint(20, 50))
                except Exception as e:
                    log.append(f"  ⚠️ Ссылка {field_n}: {str(e)[:60]}")

            time.sleep(random.uniform(0.15, 0.4))

        self._pause()

        # 12. Infringement description
        self._fill(page, [
            "textarea[name='infringement_description']",
            "textarea[name='description']",
            "textarea:last-of-type",
        ], s["infringement_desc"])

        self._pause()

        # 13. Electronic signature
        self._fill(page, [
            "input[name='signature']",
            "input[placeholder*='signature']",
            "input[placeholder*='electronic']",
        ], s["signature"])

        time.sleep(random.uniform(1.0, 2.0))

        # 14. Submit
        try:
            btn = page.locator(
                "button[type='submit'], input[type='submit'], button:has-text('Submit')"
            ).first
            btn.scroll_into_view_if_needed()
            btn.click(timeout=5000)
            time.sleep(random.uniform(2.0, 4.0))
            return True
        except Exception as e:
            log.append(f"  ❌ Submit: {str(e)[:80]}")
            return False

    # ── helpers ──────────────────────────────────────────────────
    def _fill(self, page, selectors: list[str], value: str):
        if not value:
            return
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible(timeout=2000):
                    el.scroll_into_view_if_needed()
                    el.click()
                    el.fill("")
                    el.type(value, delay=random.randint(25, 65))
                    return
            except Exception:
                continue

    def _click_any(self, page, selectors: list[str]):
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible(timeout=2000):
                    el.click()
                    return
            except Exception:
                continue

    def _pause(self):
        time.sleep(random.uniform(0.4, 1.0))
