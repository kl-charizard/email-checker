"""Telegram Bot notifications for important-email digests."""

from __future__ import annotations

import html
import logging
from typing import Any

import requests

from .config import TelegramConfig
from .email_client import EmailMessage

log = logging.getLogger(__name__)

# Telegram hard limit is 4096 chars per message
MAX_MESSAGE = 4000


class TelegramNotifier:
    def __init__(self, cfg: TelegramConfig) -> None:
        self.cfg = cfg

    @property
    def configured(self) -> bool:
        return bool(self.cfg.bot_token and self.cfg.chat_id)

    def send(self, text: str, parse_mode: str | None = "HTML") -> bool:
        if not self.cfg.enabled:
            log.debug("Telegram disabled in config; skipping send.")
            return False
        if not self.configured:
            log.warning(
                "Telegram is not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)."
            )
            return False

        url = f"https://api.telegram.org/bot{self.cfg.bot_token}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": self.cfg.chat_id,
            "text": text[:MAX_MESSAGE],
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            resp = requests.post(url, json=payload, timeout=30)
        except requests.RequestException as exc:
            log.error("Telegram send failed: %s", exc)
            return False

        if resp.status_code >= 400:
            # Retry without parse_mode if HTML/markdown is the problem
            if parse_mode:
                log.warning("Telegram rejected parse_mode=%s, retrying plain text.", parse_mode)
                return self.send(text, parse_mode=None)
            log.error("Telegram API error %s: %s", resp.status_code, resp.text[:300])
            return False

        log.info("Telegram message sent (%d chars)", len(text[:MAX_MESSAGE]))
        return True

    def send_important(self, mail: EmailMessage, summary: str, reason: str, action: str) -> bool:
        safe_from = html.escape(mail.sender or "")
        safe_subject = html.escape(mail.subject or "(no subject)")
        safe_date = html.escape(mail.date or "")
        safe_account = html.escape(mail.account or "")
        safe_summary = html.escape(summary or "")
        safe_reason = html.escape(reason or "")
        safe_action = html.escape(action or "")

        lines = [
            "🚨 <b>Important email</b>",
            f"<b>Account:</b> {safe_account}",
            f"<b>From:</b> {safe_from}",
            f"<b>Subject:</b> {safe_subject}",
            f"<b>Date:</b> {safe_date}",
        ]
        if safe_reason:
            lines += ["", f"<b>Why:</b> {safe_reason}"]
        if safe_summary:
            lines += ["", "<b>Summary:</b>", safe_summary]
        if safe_action:
            lines += ["", f"<b>Action:</b> {safe_action}"]

        return self.send("\n".join(lines))

    def send_digest(self, important: list[tuple[EmailMessage, str]], stats: dict[str, Any]) -> bool:
        if not important:
            body = "✅ <b>Email check complete</b> — no important new mail.\n"
        else:
            parts = [f"📬 <b>{len(important)} important</b> since last check:\n"]
            for i, (mail, summary) in enumerate(important[:20], 1):
                safe_subject = html.escape(mail.subject or "(no subject)")
                safe_from = html.escape(mail.sender or "")
                safe_summary = html.escape(summary or mail.preview(120))
                parts.append(f"{i}. <b>{safe_subject}</b> — {safe_from}\n{safe_summary}\n")
            body = "\n".join(parts)

        if stats:
            body += (
                f"\n<i>Checked {stats.get('total_checked', '?')} · "
                f"Important {stats.get('total_important', '?')} · "
                f"Notified {stats.get('total_notified', '?')}</i>"
            )
        return self.send(body)
