"""
Модуль для получения кода подтверждения от Facebook через IMAP (Titan Mail).

Titan Mail IMAP настройки:
  Server: imap.titan.email
  Port:   993 (SSL)
"""

import email
import imaplib
import re
import time
from email.header import decode_header
from typing import Optional, Union

IMAP_HOST = "imap.titan.email"
IMAP_PORT = 993


def _decode_str(value: Union[str, bytes], charset: Optional[str] = None) -> str:
    if isinstance(value, bytes):
        return value.decode(charset or "utf-8", errors="ignore")
    return value


def _get_body(msg) -> str:
    """Извлекает текст письма (plain text или html fallback)."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                body = _decode_str(payload, charset)
                break
        if not body:
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    body = _decode_str(payload, charset)
                    break
    else:
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or "utf-8"
        body = _decode_str(payload, charset)
    return body


def _extract_code(text: str) -> Optional[str]:
    """Ищет 6-значный числовой код в тексте письма."""
    # Сначала ищем по паттернам вида "code: 123456" или "код: 123456"
    for pattern in [
        r'(?:code|код|confirmation|подтверждения?)[^\d]{0,20}(\d{6})',
        r'\b(\d{6})\b',
    ]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def fetch_confirmation_code(
    imap_user: str,
    imap_pass: str,
    timeout: int = 90,
    poll_interval: int = 4,
    sender_filter: str = "facebook",
) -> Optional[str]:
    """
    Подключается к IMAP, ждёт письмо от Facebook с кодом подтверждения.

    :param imap_user:      Email для входа (напр. user@domain.com)
    :param imap_pass:      Пароль
    :param timeout:        Максимальное время ожидания в секундах
    :param poll_interval:  Интервал проверки почты в секундах
    :param sender_filter:  Подстрока в адресе отправителя
    :return:               6-значный код или None если не нашли
    """
    deadline = time.time() + timeout

    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        mail.login(imap_user, imap_pass)
        mail.select("INBOX")

        # Запоминаем UIDs уже существующих писем чтобы не читать старые
        _, existing = mail.search(None, "ALL")
        seen_ids = set(existing[0].split()) if existing[0] else set()

        while time.time() < deadline:
            time.sleep(poll_interval)

            # Ищем новые непрочитанные от Facebook
            _, result = mail.search(
                None,
                f'UNSEEN FROM "{sender_filter}"',
            )
            if not result[0]:
                continue

            new_ids = set(result[0].split()) - seen_ids
            if not new_ids:
                continue

            for uid in sorted(new_ids):
                _, msg_data = mail.fetch(uid, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue

                msg = email.message_from_bytes(msg_data[0][1])
                body = _get_body(msg)
                code = _extract_code(body)

                if code:
                    # Помечаем письмо как прочитанное
                    mail.store(uid, "+FLAGS", "\\Seen")
                    mail.logout()
                    return code

                seen_ids.add(uid)

        mail.logout()
    except imaplib.IMAP4.error as e:
        raise RuntimeError(f"IMAP ошибка: {e}") from e

    return None


def test_imap_connection(imap_user: str, imap_pass: str) -> tuple:
    """
    Проверяет подключение к IMAP.
    Возвращает (True, "OK") или (False, "сообщение об ошибке").
    """
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        mail.login(imap_user, imap_pass)
        mail.select("INBOX")
        mail.logout()
        return True, "Подключение успешно"
    except imaplib.IMAP4.error as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)
