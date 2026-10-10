"""Core checker loop: fetch → AI triage → memory → Telegram."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from .ai_classifier import AIClassifier, Classification
from .config import AppConfig, ensure_runtime_dirs
from .email_client import EmailClient, EmailMessage
from .memory import MemoryStore
from .telegram_notifier import TelegramNotifier

log = logging.getLogger(__name__)


class EmailChecker:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        ensure_runtime_dirs(cfg)
        self.memory = MemoryStore(cfg.memory_path, cfg.max_decisions)
        self.classifier = AIClassifier(cfg.ai)
        self.telegram = TelegramNotifier(cfg.telegram)

    # ---- public API ----

    def run_once(self) -> dict[str, int]:
        """One full pass over all enabled accounts. Returns counters."""
        since = datetime.now(timezone.utc) - timedelta(days=self.cfg.days_lookback)
        counters = {
            "fetched": 0,
            "skipped_processed": 0,
            "important": 0,
            "notified": 0,
            "errors": 0,
        }

        for account in self.cfg.accounts:
            if not account.enabled:
                log.info("Skipping disabled account: %s", account.name)
                continue
            if not account.address or not account.password:
                log.warning(
                    "Account '%s' has no credentials in .env — skipping.",
                    account.name,
                )
                continue

            try:
                self._check_account(account, since, counters)
            except Exception as exc:  # noqa: BLE001 - isolate account failures
                log.error("Account '%s' failed: %s", account.name, exc)
                counters["errors"] += 1
                self.memory.bump_error()

        self.memory.save()
        log.info(
            "Pass done: fetched=%(fetched)s skipped=%(skipped_processed)s "
            "important=%(important)s notified=%(notified)s errors=%(errors)s",
            counters,
        )
        return counters

    def run_forever(self, once: bool = False) -> None:
        interval = max(30, int(self.cfg.check_interval_seconds))
        log.info(
            "Starting email checker (interval=%ss, accounts=%s)",
            interval,
            [a.name for a in self.cfg.accounts if a.enabled],
        )
        if self.telegram.configured:
            self.telegram.send(
                "🤖 <b>Email checker started</b>\n"
                f"Interval: {interval}s · Accounts: "
                f"{', '.join(a.name for a in self.cfg.accounts if a.enabled) or 'none'}"
            )

        while True:
            try:
                self.run_once()
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                log.exception("Unhandled error in run_once: %s", exc)
                self.memory.bump_error()
                self.memory.save()
            if once:
                break
            log.info("Sleeping %ss…", interval)
            time.sleep(interval)

    # ---- internals ----

    def _check_account(self, account, since: datetime, counters: dict[str, int]) -> None:
        log.info("Checking account '%s' (%s)", account.name, account.address)
        with EmailClient(account) as client:
            mails = client.fetch_unseen(
                folders=self.cfg.folders,
                since=since,
                limit=self.cfg.max_emails_per_check,
            )
            log.info("'%s': %d candidate email(s)", account.name, len(mails))

            for mail in mails:
                key = mail.message_id or mail.uid
                if self.memory.is_processed(account.name, key) or self.memory.is_processed(
                    account.name, mail.uid
                ):
                    counters["skipped_processed"] += 1
                    continue

                counters["fetched"] += 1
                try:
                    result = self.classifier.classify(mail, self.cfg.importance_criteria)
                except Exception as exc:  # noqa: BLE001
                    log.error("AI classification failed for '%s': %s", mail.subject, exc)
                    counters["errors"] += 1
                    self.memory.bump_error()
                    # Do not mark processed so we can retry next pass
                    continue

                notified = False
                if result.important:
                    counters["important"] += 1
                    notified = self.telegram.send_important(
                        mail,
                        summary=result.summary or mail.preview(300),
                        reason=result.reason,
                        action=result.action_needed,
                    )
                    if notified:
                        counters["notified"] += 1
                elif self.cfg.telegram.send_non_important_digest:
                    # Optionally surface low-priority as a quiet line
                    self.telegram.send(
                        f"ℹ️ Not important: <b>{_esc(mail.subject)}</b> — {_esc(result.reason)}"
                    )

                self.memory.add_decision(
                    account=account.name,
                    uid=mail.uid,
                    message_id=mail.message_id,
                    sender=mail.sender,
                    subject=mail.subject,
                    date=mail.date,
                    important=result.important,
                    reason=result.reason,
                    summary=result.summary,
                    notified=notified,
                )
                self.memory.mark_processed(account.name, mail.message_id or mail.uid)
                self.memory.mark_processed(account.name, mail.uid)
                self.memory.save()
                # Intentionally do NOT mark as read — user keeps \Unseen in their client.
                # Dedup is handled by memory.json (processed UIDs / Message-IDs).
                # Fetch uses BODY.PEEK so the mailbox flags are never touched.


def _esc(text: str) -> str:
    import html

    return html.escape(text or "")
