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
EMAIL_CODE_TIMEOUT = 180

# Maps user-entered work type (RU or EN) → English option value used by Facebook's select
WORK_TYPE_MAP = {
    "фото": "Photo",   "photo": "Photo",
    "видео": "Video",  "video": "Video",
    "текст": "Text",   "text": "Text",
    "другое": "Other", "other": "Other",
}


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
        imap_user = s.get("imap_user", "").strip()
        imap_pass = s.get("imap_pass", "").strip()

        # Connect to IMAP BEFORE submitting the form so we don't miss fast-arriving emails
        imap_baseline = 0
        if imap_user and imap_pass:
            try:
                import imaplib as _imap
                _m = _imap.IMAP4_SSL("imap.titan.email", 993)
                _m.login(imap_user, imap_pass)
                _m.select("INBOX")
                _, _ex = _m.search(None, "ALL")
                _ids = _ex[0].split() if _ex[0] else []
                imap_baseline = int(_ids[-1]) if _ids else 0
                _m.logout()
                log.append(f"  📬 IMAP готов (последнее письмо #{imap_baseline})")
            except Exception as e:
                log.append(f"  ⚠️ IMAP предподключение: {str(e)[:80]}")

        log.append("  → Открываю форму...")
        page.goto(FORM_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)

        # ── 1. I am the rights owner ──────────────────────────────
        # JS click bypasses the <span> overlay on Facebook's custom radio buttons.
        # Input name/value attributes are always English regardless of FB UI language.
        log.append("  → Выбираю: I am the rights owner")
        page.locator('input[name="copyright_owner"][value="I am the rights owner."]').evaluate("el => el.click()")
        page.locator('input[name="your_name"]').wait_for(state="visible", timeout=12000)
        self._pause(0.5, 1.0)

        # ── 2. Full name ──────────────────────────────────────────
        log.append("  → Заполняю: Full name")
        page.locator('input[name="your_name"]').fill(s["full_name"])
        self._pause(0.3, 0.5)

        # ── 3. Email ──────────────────────────────────────────────
        log.append("  → Заполняю: Email")
        page.locator('input[name="email"]').fill(s["email"])
        self._pause(0.3, 0.5)

        # ── 4. Confirm email ──────────────────────────────────────
        log.append("  → Заполняю: Confirm email")
        page.locator('input[name="confirm_email"]').fill(s["email"])
        self._pause(0.3, 0.5)

        # ── 5. Country ────────────────────────────────────────────
        # Select option by value (always English) — not label (changes with FB UI language)
        log.append(f"  → Выбираю страну: {s['country']}")
        page.locator('select[name="rights_owner_country_routing"]').select_option(value=s["country"])
        self._pause(0.3, 0.5)

        # ── 6. Work type ──────────────────────────────────────────
        work_type = s["work_type"].split(",")[0].strip() if s.get("work_type") else ""
        if work_type:
            log.append(f"  → Выбираю тип: {work_type}")
            wt_value = WORK_TYPE_MAP.get(work_type.lower(), work_type)
            try:
                page.locator('select[name="describe_copyrighted_work_me"]').select_option(value=wt_value)
            except Exception:
                try:
                    page.locator('select[name="describe_copyrighted_work_me"]').select_option(label=work_type)
                except Exception:
                    log.append(f"  ⚠️ Тип '{work_type}' не найден, пропускаю")
        self._pause(0.3, 0.5)

        # ── 7. Rights owner name ─────────────────────────────────
        log.append("  → Заполняю: Rights owner name")
        page.locator('input[name="reporter_name"]').fill(s["rights_owner_name"])
        self._pause(0.3, 0.5)

        # ── 8. Link to copyrighted work ───────────────────────────
        log.append("  → Заполняю: Ссылка на оригинал")
        page.locator('input[name="copyright_url"]').fill(self.account_url)
        self._pause(0.3, 0.5)

        # ── 9. Describe copyrighted work ─────────────────────────
        log.append("  → Заполняю: Описание произведения")
        page.locator('textarea[name="describe_copyrighted_work_me_URLs"]').fill(s["work_description"])
        self._pause(0.5, 0.8)

        # ── 10. Content type = Photo, video or post ───────────────
        log.append("  → Выбираю: Photo, video or post")
        page.locator('input[name="Content_type[]"][value="Photo, video or post"]').evaluate("el => el.click()")
        self._pause(0.5, 0.8)

        # ── 11. Ссылки на посты ───────────────────────────────────
        # Links are textareas: content_urls (link 1), content_urls1 (link 2), ..., content_urls29 (link 30)
        log.append(f"  → Заполняю {len(batch)} ссылок...")
        for idx, url in enumerate(batch):
            if idx == 10:
                try:
                    cb = page.locator('input[name="additionallinks[]"]')
                    if cb.count() > 0 and not cb.is_checked(timeout=2000):
                        cb.evaluate("el => el.click()")
                        time.sleep(0.5)
                except Exception:
                    pass

            try:
                field_name = "content_urls" if idx == 0 else f"content_urls{idx}"
                field = page.locator(f'textarea[name="{field_name}"]')
                field.scroll_into_view_if_needed()
                field.fill(url)
            except Exception as e:
                log.append(f"  ⚠️ Ссылка {idx+1}: {str(e)[:60]}")

            time.sleep(random.uniform(0.1, 0.25))

        self._pause(0.5, 0.8)

        # ── 12. Infringement description ──────────────────────────
        log.append("  → Заполняю: Описание нарушения")
        page.locator('textarea[name="why_reporting_other"]').fill(s["infringement_desc"])
        self._pause(0.5, 0.8)

        # ── 13. Electronic signature ──────────────────────────────
        log.append("  → Заполняю: Подпись")
        page.locator('input[name="Electronic_sig"]').fill(s["signature"])
        time.sleep(random.uniform(0.8, 1.5))

        # ── 14. Submit ────────────────────────────────────────────
        log.append("  → Нажимаю Submit...")
        submitted = False
        for btn_name in ["Отправить", "Submit"]:
            try:
                page.get_by_role("button", name=btn_name).click(timeout=5000)
                submitted = True
                break
            except Exception:
                continue

        if not submitted:
            log.append("  ❌ Кнопка Submit не найдена")
            return False

        time.sleep(random.uniform(2.0, 3.5))

        # Log URL and title to confirm submission page
        log.append(f"  🌐 URL: {page.url}")
        log.append(f"  📄 Заголовок: {page.title()}")
        try:
            screenshot_path = Path(__file__).parent / "cookies" / "submit_result.png"
            page.screenshot(path=str(screenshot_path))
            log.append("  📸 Скриншот: cookies/submit_result.png")
        except Exception:
            pass

        # ── 15. Код подтверждения из email ────────────────────────
        if imap_user and imap_pass:
            log.append(f"  📬 Ожидаю код на {imap_user} (базовый ID: {imap_baseline})...")
            try:
                code = fetch_confirmation_code(
                    imap_user, imap_pass,
                    timeout=EMAIL_CODE_TIMEOUT,
                    min_uid=imap_baseline,
                )
            except RuntimeError as e:
                log.append(f"  ⚠️ IMAP: {str(e)[:100]}")
                code = None

            if code:
                log.append(f"  ✉️ Код: {code}")
                entered = False
                for sel in [
                    "input[placeholder*='код']",
                    "input[placeholder*='code']",
                    "input[placeholder*='Отправьте']",
                    "input[name='confirmation_code']",
                    "input[name='code']",
                    "input[maxlength='6']",
                ]:
                    try:
                        el = page.locator(sel).first
                        if el.count() > 0 and el.is_visible(timeout=2000):
                            el.fill(code)
                            time.sleep(0.5)
                            entered = True
                            break
                    except Exception:
                        continue

                if not entered:
                    log.append("  ⚠️ Поле для кода не найдено")
                else:
                    # Click confirm button (Подтвердить or Submit)
                    for btn_name in ["Подтвердить", "Отправить", "Submit", "Confirm"]:
                        try:
                            page.get_by_role("button", name=btn_name).click(timeout=5000)
                            log.append(f"  ✅ Код введён, нажата кнопка «{btn_name}»")
                            # Wait for page to navigate away from the popup
                            try:
                                page.wait_for_url(
                                    lambda url: "help/contact" not in url or "sent" in url.lower(),
                                    timeout=10000,
                                )
                            except Exception:
                                time.sleep(8.0)
                            log.append(f"  🌐 После кода URL: {page.url}")
                            log.append(f"  📄 После кода заголовок: {page.title()}")
                            try:
                                page.screenshot(path=str(
                                    Path(__file__).parent / "cookies" / "submit_result.png"
                                ))
                            except Exception:
                                pass
                            break
                        except Exception:
                            continue
            else:
                log.append(f"  ⚠️ Код не пришёл за {EMAIL_CODE_TIMEOUT}с")

        return True

    # ── helpers ──────────────────────────────────────────────────
    def _pause(self, mn: float = 0.4, mx: float = 1.0):
        time.sleep(random.uniform(mn, mx))
