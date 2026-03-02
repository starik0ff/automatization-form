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
    """Извлекает текст письма. Возвращает plain text + HTML stripped (оба варианта)."""
    import re as _re
    parts_text = []
    parts_html = []

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if "attachment" in cd:
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            decoded = _decode_str(payload, charset)
            if ct == "text/plain":
                parts_text.append(decoded)
            elif ct == "text/html":
                parts_html.append(decoded)
    else:
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or "utf-8"
        decoded = _decode_str(payload, charset)
        ct = msg.get_content_type()
        if ct == "text/html":
            parts_html.append(decoded)
        else:
            parts_text.append(decoded)

    # Strip HTML tags to plain text for searching
    html_as_text = ""
    for h in parts_html:
        html_as_text += _re.sub(r"<[^>]+>", " ", h)

    # Return plain text first, then html-stripped — concatenated so regex can search both
    return "\n".join(parts_text) + "\n" + html_as_text


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
    timeout: int = 180,
    poll_interval: int = 4,
    sender_filter: str = "facebook",
    min_uid: int = 0,
) -> Optional[str]:
    """
    Подключается к IMAP, ждёт письмо от Facebook/Meta с кодом подтверждения.
    Проверяет INBOX и папки спама (Spam, Junk).

    :param min_uid:        Минимальный UID письма (игнорируем письма старше этого)
    """
    # Folders to check in priority order
    FOLDERS_TO_CHECK = ["INBOX", "Spam", "Junk", "Junk Email", "INBOX.Spam", "INBOX.Junk"]

    deadline = time.time() + timeout

    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        mail.login(imap_user, imap_pass)

        # Find available folders that exist on this server
        _, folder_list = mail.list()
        available_folders = []
        for f in folder_list or []:
            decoded = f.decode() if isinstance(f, bytes) else f
            # Extract folder name (last part after space or quoted)
            parts = decoded.split('"')
            fname = parts[-1].strip() if len(parts) > 1 else decoded.split()[-1]
            available_folders.append(fname)

        folders = [f for f in FOLDERS_TO_CHECK if f in available_folders]
        if "INBOX" not in folders:
            folders.insert(0, "INBOX")

        # Facebook sends verification emails from @facebookmail.com and @email.meta.com
        sender_filters = [sender_filter, "meta", "facebookmail"]
        processed: set = set()

        while time.time() < deadline:
            time.sleep(poll_interval)

            for folder in folders:
                try:
                    mail.select(folder)

                    # Search ALL (not just UNSEEN) — PEEK fetch won't mark as read anyway
                    candidate_ids: set = set()
                    for sf in sender_filters:
                        _, result = mail.search(None, f'ALL FROM "{sf}"')
                        if result[0]:
                            candidate_ids.update(result[0].split())

                    # Only consider emails newer than baseline recorded before form submit
                    new_ids = {
                        uid for uid in candidate_ids
                        if int(uid) > min_uid and uid not in processed
                    }

                    for uid in sorted(new_ids, reverse=True):  # newest first
                        _, msg_data = mail.fetch(uid, "(BODY.PEEK[])")  # PEEK = don't mark as read
                        if not msg_data or not msg_data[0]:
                            continue

                        msg = email.message_from_bytes(msg_data[0][1])
                        body = _get_body(msg)
                        code = _extract_code(body)
                        processed.add(uid)

                        if code:
                            mail.logout()
                            return code

                except Exception:
                    continue

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
