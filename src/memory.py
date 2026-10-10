"""JSON-backed memory: processed email IDs, AI decisions, and light stats.

Everything lives in one JSON file inside the project folder (default: data/memory.json).
Safe to inspect, backup, or feed into another tool later.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    def __init__(self, path: Path, max_decisions: int = 2000) -> None:
        self.path = Path(path)
        self.max_decisions = max_decisions
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {
            "version": 1,
            "created_at": _now(),
            "updated_at": _now(),
            "processed": {},  # account -> {uid_key: timestamp}
            "decisions": [],
            "stats": {
                "total_checked": 0,
                "total_important": 0,
                "total_notified": 0,
                "total_errors": 0,
            },
        }
        self._load()

    # ---- persistence ----

    def _load(self) -> None:
        if self.path.exists():
            try:
                with self.path.open("r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, dict):
                    self._data.update(loaded)
                    self._data.setdefault("processed", {})
                    self._data.setdefault("decisions", [])
                    self._data.setdefault("stats", {})
            except (json.JSONDecodeError, OSError):
                # Keep a backup of the corrupt file and start clean
                backup = self.path.with_suffix(".corrupt.json")
                try:
                    self.path.replace(backup)
                except OSError:
                    pass

    def save(self) -> None:
        with self._lock:
            self._data["updated_at"] = _now()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, ensure_ascii=False)
            tmp.replace(self.path)

    # ---- processed tracking ----

    def is_processed(self, account: str, uid: str | int) -> bool:
        uid_key = str(uid)
        return uid_key in self._data.get("processed", {}).get(account, {})

    def mark_processed(self, account: str, uid: str | int) -> None:
        uid_key = str(uid)
        self._data.setdefault("processed", {}).setdefault(account, {})[uid_key] = _now()

    def clear_processed(self, account: str | None = None) -> int:
        if account is None:
            n = sum(len(v) for v in self._data.get("processed", {}).values())
            self._data["processed"] = {}
            return n
        bucket = self._data.get("processed", {}).get(account, {})
        n = len(bucket)
        self._data.setdefault("processed", {})[account] = {}
        return n

    # ---- decisions ----

    def add_decision(
        self,
        *,
        account: str,
        uid: str | int,
        message_id: str,
        sender: str,
        subject: str,
        date: str,
        important: bool,
        reason: str,
        summary: str,
        notified: bool = False,
    ) -> dict[str, Any]:
        record = {
            "account": account,
            "uid": str(uid),
            "message_id": message_id,
            "from": sender,
            "subject": subject,
            "date": date,
            "important": important,
            "reason": reason,
            "summary": summary,
            "notified": notified,
            "checked_at": _now(),
        }
        with self._lock:
            self._data.setdefault("decisions", []).append(record)
            # Trim oldest decisions if over cap
            decisions = self._data["decisions"]
            if len(decisions) > self.max_decisions:
                self._data["decisions"] = decisions[-self.max_decisions :]
            stats = self._data.setdefault("stats", {})
            stats["total_checked"] = int(stats.get("total_checked", 0)) + 1
            if important:
                stats["total_important"] = int(stats.get("total_important", 0)) + 1
            if notified:
                stats["total_notified"] = int(stats.get("total_notified", 0)) + 1
        return record

    def mark_notified(self, account: str, uid: str | int) -> None:
        uid_key = str(uid)
        with self._lock:
            for rec in reversed(self._data.setdefault("decisions", [])):
                if rec.get("account") == account and str(rec.get("uid")) == uid_key:
                    if not rec.get("notified"):
                        rec["notified"] = True
                        stats = self._data.setdefault("stats", {})
                        stats["total_notified"] = int(stats.get("total_notified", 0)) + 1
                    break

    def bump_error(self) -> None:
        with self._lock:
            stats = self._data.setdefault("stats", {})
            stats["total_errors"] = int(stats.get("total_errors", 0)) + 1

    # ---- queries ----

    def recent_decisions(self, limit: int = 20, important_only: bool = False) -> list[dict[str, Any]]:
        items = self._data.get("decisions", [])
        if important_only:
            items = [d for d in items if d.get("important")]
        return items[-limit:][::-1]

    def stats(self) -> dict[str, Any]:
        return dict(self._data.get("stats", {}))

    def export_json(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._data))
