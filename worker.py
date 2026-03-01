import json
import platform
import random
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from email_reader import fetch_confirmation_code

# На Linux (сервер) — headless автоматически
IS_HEADLESS = platform.system() == "Linux"

FORM_URL        = "https://www.facebook.com/help/contact/1758255661104383"
LINKS_PER_BATCH = 30
DELAY_MIN       = 8
DELAY_MAX       = 18
EMAIL_CODE_TIMEOUT = 90


class BotWorker:
    def __init__(self, account_url: str, post_urls: list, static: dict,
                 status_file: Path, on_finish=None):
        self.account_url = account_url
        self.post_urls   = post_urls
        self.static      = static
        self.status_file = status_file
        self.on_finish   = on_finish
        self._stop       = False
        self.batches     = [
            post_urls[i:i + LINKS_PER_BATCH]
            for i in range(0, len(post_urls), LINKS_PER_BATCH)
        ]

    def stop(self):
        self._stop = True

    def _save(self, state: str, done: int, failed: int, log: list):
        with open(self.status_file, "w") as f:
            json.dump({
                "state":  state,
                "total":  len(self.post_urls),
                "done":   done,
                "failed": failed,
                "log":    log[-100:],
            }, f, ensure_ascii=False)

    def run(self):
        log    = [f"Постов: {len(self.post_urls)}, батчей: {len(self.batches)} (по {LINKS_PER_BATCH})"]
        done   = 0
        failed = 0

        session_path = Path(__file__).parent / "cookies" / "session.json"
        if not session_path.exists():
            log.append("⚠️  Сессия не найдена. Запусти save_session.py")
            self._save("error", done, failed, log)
            return

        self._save("running", done, failed, log)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=IS_HEADLESS)
                context = browser.new_context(
                    storage_state=str(session_path.resolve()),
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
    def _submit_batch(self, page, batch: list, log: list) -> bool:
        s = self.static

        log.append("  → Открываю форму...")
        page.goto(FORM_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)

        # ── 1. I am the rights owner ──────────────────────────────
        log.append("  → Выбираю: I am the rights owner")
        page.get_by_text("I am the rights owner.", exact=True).click()
        # Ждём появления поля Full name через get_by_label (он сам ждёт до 10с)
        page.get_by_label("Your full name").wait_for(timeout=12000)
        self._pause(0.5, 1.0)

        # ── 2. Full name ──────────────────────────────────────────
        log.append("  → Заполняю: Full name")
        page.get_by_label("Your full name").fill(s["full_name"])
        self._pause(0.3, 0.5)

        # ── 3. Email ──────────────────────────────────────────────
        log.append("  → Заполняю: Email")
        # Берём первый input типа email на странице
        page.locator("input[type='email']").first.fill(s["email"])
        self._pause(0.3, 0.5)

        # ── 4. Confirm email ──────────────────────────────────────
        log.append("  → Заполняю: Confirm email")
        page.locator("input[type='email']").nth(1).fill(s["email"])
        self._pause(0.3, 0.5)

        # ── 5. Country ────────────────────────────────────────────
        log.append(f"  → Выбираю страну: {s['country']}")
        page.get_by_label("Where are you asserting rights?").select_option(label=s["country"])
        self._pause(0.3, 0.5)

        # ── 6. Work type ──────────────────────────────────────────
        work_type = s["work_type"].split(",")[0].strip() if s["work_type"] else ""
        if work_type:
            log.append(f"  → Выбираю тип: {work_type}")
            page.get_by_label("Which of these best describes the copyrighted work?").select_option(
                label=work_type
            )
        self._pause(0.3, 0.5)

        # ── 7. Rights owner name ─────────────────────────────────
        log.append("  → Заполняю: Rights owner name")
        page.get_by_label("Name of the rights owner", exact=False).fill(s["rights_owner_name"])
        self._pause(0.3, 0.5)

        # ── 8. Link to copyrighted work ───────────────────────────
        log.append("  → Заполняю: Ссылка на оригинал")
        page.get_by_label("Provide a link to the copyrighted work", exact=False).fill(self.account_url)
        self._pause(0.3, 0.5)

        # ── 9. Describe copyrighted work ─────────────────────────
        log.append("  → Заполняю: Описание произведения")
        page.get_by_label("Describe your copyrighted work", exact=False).fill(s["work_description"])
        self._pause(0.5, 0.8)

        # ── 10. Content type = Photo, video or post ───────────────
        log.append("  → Выбираю: Photo, video or post")
        page.get_by_text("Photo, video or post", exact=True).click()
        self._pause(0.5, 0.8)

        # ── 11. Ссылки на посты ───────────────────────────────────
        log.append(f"  → Заполняю {len(batch)} ссылок...")
        for idx, url in enumerate(batch):
            field_n = idx + 1

            if idx == 10:
                try:
                    more = page.get_by_text("I have additional links to report", exact=True)
                    if more.is_visible(timeout=2000):
                        more.click()
                        time.sleep(0.5)
                except Exception:
                    pass

            try:
                if field_n == 1:
                    field = page.get_by_placeholder("https://www.facebook.com/…").first
                else:
                    field = page.get_by_label(f"Link {field_n}", exact=True)

                field.scroll_into_view_if_needed()
                field.fill(url)
            except Exception as e:
                log.append(f"  ⚠️ Ссылка {field_n}: {str(e)[:60]}")

            time.sleep(random.uniform(0.1, 0.25))

        self._pause(0.5, 0.8)

        # ── 12. Infringement description ──────────────────────────
        log.append("  → Заполняю: Описание нарушения")
        page.get_by_label("Describe how you believe this content infringes", exact=False).fill(
            s["infringement_desc"]
        )
        self._pause(0.5, 0.8)

        # ── 13. Electronic signature ──────────────────────────────
        log.append("  → Заполняю: Подпись")
        page.get_by_label("Electronic signature", exact=False).fill(s["signature"])
        time.sleep(random.uniform(0.8, 1.5))

        # ── 14. Submit ────────────────────────────────────────────
        log.append("  → Нажимаю Submit...")
        try:
            page.get_by_role("button", name="Submit").click(timeout=5000)
            time.sleep(random.uniform(2.0, 3.5))
        except Exception as e:
            log.append(f"  ❌ Submit: {str(e)[:80]}")
            return False

        # ── 15. Код подтверждения из email ────────────────────────
        imap_user = s.get("imap_user", "").strip()
        imap_pass = s.get("imap_pass", "").strip()

        if imap_user and imap_pass:
            log.append(f"  📬 Ожидаю код на {imap_user}...")
            try:
                code = fetch_confirmation_code(imap_user, imap_pass, timeout=EMAIL_CODE_TIMEOUT)
            except RuntimeError as e:
                log.append(f"  ⚠️ IMAP: {str(e)[:100]}")
                code = None

            if code:
                log.append(f"  ✉️ Код: {code}")
                for sel in [
                    "input[name='confirmation_code']",
                    "input[name='code']",
                    "input[maxlength='6']",
                    "input[placeholder*='code']",
                ]:
                    try:
                        el = page.locator(sel).first
                        if el.count() > 0 and el.is_visible(timeout=2000):
                            el.fill(code)
                            time.sleep(0.5)
                            page.get_by_role("button", name="Submit").click(timeout=5000)
                            time.sleep(2.0)
                            break
                    except Exception:
                        continue
            else:
                log.append(f"  ⚠️ Код не пришёл за {EMAIL_CODE_TIMEOUT}с")

        return True

    # ── helpers ──────────────────────────────────────────────────
    def _pause(self, mn: float = 0.4, mx: float = 1.0):
        time.sleep(random.uniform(mn, mx))
