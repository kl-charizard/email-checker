"""IMAP email fetch for Gmail and Outlook (and any IMAP host).

Uses only the Python standard library (imaplib + email) so it runs cleanly
on Raspberry Pi, Linux, macOS, and Windows.

Messages are read with BODY.PEEK[] and folders are opened readonly —
the checker never sets \\Seen, so mail stays unread for the user.
"""

from __future__ import annotations

import email
import email.header
import email.message
import email.utils
import imaplib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from .config import AccountConfig

log = logging.getLogger(__name__)

# Increase IMAP line limit a bit for large messages (Pi-friendly)
imaplib._MAXLINE = 100_000  # type: ignore[attr-defined]


@dataclass
class EmailMessage:
    uid: str
    message_id: str
    subject: str
    sender: str
    to: str
    date: str
    body: str
    account: str

    def preview(self, n: int = 160) -> str:
        text = re.sub(r"\s+", " ", self.body or "").strip()
        return text[:n] + ("…" if len(text) > n else "")


def _decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    parts = email.header.decode_header(value)
    out: list[str] = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            out.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(chunk)
    return "".join(out).strip()


def _extract_body(msg: email.message.Message) -> str:
    """Prefer text/plain, fall back to a simple HTML strip."""
    plain: list[str] = []
    html: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp.lower():
                continue
            if ctype == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    plain.append(payload.decode(charset, errors="replace"))
            elif ctype == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    html.append(payload.decode(charset, errors="replace"))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html.append(text)
            else:
                plain.append(text)

    if plain:
        return "\n".join(plain).strip()
    if html:
        return _html_to_text("\n".join(html))
    return ""


def _html_to_text(html: str) -> str:
    # Lightweight strip — no external HTML parser required.
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&#39;|&apos;", "'", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class EmailClient:
    def __init__(self, account: AccountConfig) -> None:
        self.account = account
        self._conn: imaplib.IMAP4_SSL | None = None

    def connect(self) -> None:
        if not self.account.address or not self.account.password:
            raise RuntimeError(
                f"Account '{self.account.name}' is missing address/password. "
                "Fill GMAIL_ADDRESS / GMAIL_APP_PASSWORD (or OUTLOOK_*) in .env"
            )
        host = self.account.imap_host
        port = self.account.imap_port
        if not host:
            raise RuntimeError(f"Account '{self.account.name}' has no IMAP host configured.")
        log.info("Connecting to %s (%s)", host, self.account.address)
        self._conn = imaplib.IMAP4_SSL(host, port)
        try:
            self._conn.login(self.account.address, self.account.password)
        except imaplib.IMAP4.error as exc:
            raw = str(exc)
            if "Basic authentication is disabled" in raw or "AUTHENTICATIONFAILED" in raw:
                if self.account.provider == "outlook":
                    raise RuntimeError(
                        f"Outlook login failed for {self.account.address}: {raw}\n"
                        "  Microsoft often blocks plain passwords.\n"
                        "  Fix: use an App Password (account.live.com/proofs/AppPassword)\n"
                        "  on a personal @outlook.com/@hotmail.com account with 2FA on.\n"
                        "  Work/school Office 365 tenants usually require OAuth2 and may\n"
                        "  not work with this IMAP login — try Gmail for those, or an\n"
                        "  IMAP-enabled mailbox that still accepts app passwords."
                    ) from exc
                if self.account.provider == "gmail":
                    raise RuntimeError(
                        f"Gmail login failed for {self.account.address}: {raw}\n"
                        "  Fix: enable 2-Step Verification, then create an App Password:\n"
                        "  Google Account → Security → 2-Step Verification → App passwords\n"
                        "  Put the 16-character password in GMAIL_APP_PASSWORD (.env)."
                    ) from exc
            raise

    def disconnect(self) -> None:
        if self._conn is not None:
            try:
                self._conn.logout()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
            self._conn = None

    def __enter__(self) -> "EmailClient":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.disconnect()

    def fetch_unseen(
        self,
        folders: Iterable[str] = ("INBOX",),
        since: datetime | None = None,
        limit: int = 25,
    ) -> list[EmailMessage]:
        if self._conn is None:
            raise RuntimeError("Not connected. Use connect() or a with-block.")

        if since is None:
            since = datetime.now(timezone.utc) - timedelta(days=7)
        # IMAP SINCE uses day granularity (01-Jan-2024)
        since_str = since.strftime("%d-%b-%Y")

        collected: list[EmailMessage] = []
        for folder in folders:
            status, _ = self._conn.select(folder, readonly=True)
            if status != "OK":
                log.warning("Cannot select folder %s on %s", folder, self.account.name)
                continue

            # Search unseen messages since the lookback date
            status, data = self._conn.search(None, f'(UNSEEN SINCE "{since_str}")')
            if status != "OK" or not data or not data[0]:
                continue

            uids = data[0].split()
            # Oldest first, then cap
            uids = uids[:limit]
            if not uids:
                continue

            log.info(
                "%s/%s: %d unseen candidate(s)",
                self.account.name,
                folder,
                len(uids),
            )

            for uid in uids:
                try:
                    msg = self._fetch_one(folder, uid)
                    if msg:
                        collected.append(msg)
                except Exception as exc:  # noqa: BLE001 - keep scanning other mails
                    log.warning(
                        "Failed to fetch uid=%s on %s: %s",
                        uid.decode() if isinstance(uid, bytes) else uid,
                        self.account.name,
                        exc,
                    )

        # Newest first
        collected.sort(key=lambda m: m.date or "", reverse=True)
        return collected

    def _fetch_one(self, folder: str, uid: bytes) -> EmailMessage | None:
        assert self._conn is not None
        status, data = self._conn.fetch(uid, "(BODY.PEEK[])")
        if status != "OK" or not data or data[0] is None:
            return None

        raw = data[0][1] if isinstance(data[0], tuple) else b""
        if not raw:
            return None

        msg = email.message_from_bytes(raw)
        uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
        message_id = _decode_mime_header(msg.get("Message-Id") or msg.get("Message-ID")) or uid_str
        subject = _decode_mime_header(msg.get("Subject")) or "(no subject)"
        sender = _decode_mime_header(msg.get("From"))
        to = _decode_mime_header(msg.get("To"))
        date = _decode_mime_header(msg.get("Date"))
        body = _extract_body(msg)

        return EmailMessage(
            uid=uid_str,
            message_id=message_id,
            subject=subject,
            sender=sender,
            to=to,
            date=date,
            body=body,
            account=self.account.name,
        )
