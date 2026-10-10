"""Configuration loading.

All secrets come from environment variables / .env.
Non-secret settings come from config.json (copied from config.example.json).
All relative paths resolve inside the project folder so nothing is written outside it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional at import time
    load_dotenv = None  # type: ignore[assignment]

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _project_path(rel: str | Path) -> Path:
    """Resolve a path inside the project folder."""
    p = Path(rel)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


@dataclass
class AccountConfig:
    name: str
    provider: str  # "gmail" | "outlook" | "imap"
    enabled: bool = True
    address: str = ""
    password: str = ""
    imap_host: str = ""
    imap_port: int = 993


@dataclass
class AIConfig:
    provider: str = "openai"  # "openai" | "anthropic"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-haiku-latest"
    timeout_seconds: int = 60
    max_body_chars: int = 6000


@dataclass
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""
    enabled: bool = True
    send_non_important_digest: bool = False


@dataclass
class AppConfig:
    check_interval_seconds: int = 300
    max_emails_per_check: int = 25
    days_lookback: int = 7
    importance_criteria: str = (
        "Mark as important only if a human needs a reply, decision, or action from me. "
        "Ignore marketing, newsletters, and automated noise."
    )
    accounts: list[AccountConfig] = field(default_factory=list)
    folders: list[str] = field(default_factory=lambda: ["INBOX"])
    ai: AIConfig = field(default_factory=AIConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    memory_path: Path = field(default_factory=lambda: _project_path("data/memory.json"))
    max_decisions: int = 2000
    log_level: str = "INFO"
    log_path: Path = field(default_factory=lambda: _project_path("logs/checker.log"))


IMAP_HOSTS = {
    "gmail": ("imap.gmail.com", 993),
    "outlook": ("outlook.office365.com", 993),
}


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load config.json + environment variables into AppConfig."""
    if load_dotenv is not None:
        load_dotenv(_project_path(".env"))

    path = _project_path(config_path or "config.json")
    if not path.exists():
        example = _project_path("config.example.json")
        if example.exists():
            path = example
        else:
            raise FileNotFoundError(
                f"Missing {path}. Copy config.example.json to config.json and edit it."
            )

    with path.open("r", encoding="utf-8") as fh:
        raw: dict[str, Any] = json.load(fh)

    ai_raw = raw.get("ai") or {}
    ai = AIConfig(
        provider=os.getenv("AI_PROVIDER", "openai").lower(),
        api_key=os.getenv("AI_API_KEY", ""),
        base_url=os.getenv("AI_BASE_URL", ai_raw.get("base_url", "https://api.openai.com/v1")),
        model=os.getenv("AI_MODEL", ai_raw.get("model", "gpt-4o-mini")),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
        timeout_seconds=int(ai_raw.get("timeout_seconds", 60)),
        max_body_chars=int(ai_raw.get("max_body_chars", 6000)),
    )

    tg_raw = raw.get("telegram") or {}
    telegram = TelegramConfig(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        enabled=bool(tg_raw.get("enabled", True)),
        send_non_important_digest=bool(tg_raw.get("send_non_important_digest", False)),
    )

    memory_raw = raw.get("memory") or {}
    log_raw = raw.get("logging") or {}

    cfg = AppConfig(
        check_interval_seconds=int(raw.get("check_interval_seconds", 300)),
        max_emails_per_check=int(raw.get("max_emails_per_check", 25)),
        days_lookback=int(raw.get("days_lookback", 7)),
        importance_criteria=str(
            raw.get(
                "importance_criteria",
                "Mark as important only if a human needs a reply, decision, or action from me.",
            )
        ),
        folders=list(raw.get("folders") or ["INBOX"]),
        ai=ai,
        telegram=telegram,
        memory_path=_project_path(memory_raw.get("path", "data/memory.json")),
        max_decisions=int(memory_raw.get("max_decisions", 2000)),
        log_level=str(log_raw.get("level", "INFO")),
        log_path=_project_path(log_raw.get("path", "logs/checker.log")),
    )

    accounts: list[AccountConfig] = []
    for item in raw.get("accounts") or []:
        name = str(item.get("name") or item.get("provider") or "account")
        provider = str(item.get("provider") or name).lower()
        enabled = bool(item.get("enabled", True))

        if provider in ("gmail", "google"):
            address = os.getenv("GMAIL_ADDRESS", item.get("address", ""))
            password = os.getenv("GMAIL_APP_PASSWORD", item.get("password", ""))
            host, port = IMAP_HOSTS["gmail"]
            provider = "gmail"
        elif provider in ("outlook", "microsoft", "hotmail", "office365"):
            address = os.getenv("OUTLOOK_ADDRESS", item.get("address", ""))
            password = os.getenv("OUTLOOK_APP_PASSWORD", item.get("password", ""))
            host, port = IMAP_HOSTS["outlook"]
            provider = "outlook"
        else:
            address = os.getenv(f"{name.upper()}_ADDRESS", item.get("address", ""))
            password = os.getenv(f"{name.upper()}_APP_PASSWORD", item.get("password", ""))
            host = item.get("imap_host", "")
            port = int(item.get("imap_port", 993))
            provider = "imap"

        accounts.append(
            AccountConfig(
                name=name,
                provider=provider,
                enabled=enabled,
                address=address,
                password=password,
                imap_host=str(item.get("imap_host", host)),
                imap_port=int(item.get("imap_port", port)),
            )
        )

    if not accounts:
        # Sensible defaults so the app still runs after filling .env only
        g_addr = os.getenv("GMAIL_ADDRESS", "")
        o_addr = os.getenv("OUTLOOK_ADDRESS", "")
        if g_addr:
            host, port = IMAP_HOSTS["gmail"]
            accounts.append(
                AccountConfig(
                    name="gmail",
                    provider="gmail",
                    address=g_addr,
                    password=os.getenv("GMAIL_APP_PASSWORD", ""),
                    imap_host=host,
                    imap_port=port,
                )
            )
        if o_addr:
            host, port = IMAP_HOSTS["outlook"]
            accounts.append(
                AccountConfig(
                    name="outlook",
                    provider="outlook",
                    address=o_addr,
                    password=os.getenv("OUTLOOK_APP_PASSWORD", ""),
                    imap_host=host,
                    imap_port=port,
                )
            )

    cfg.accounts = accounts
    return cfg


def ensure_runtime_dirs(cfg: AppConfig) -> None:
    """Create project-local data/log directories. Never write outside the project."""
    cfg.memory_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.log_path.parent.mkdir(parents=True, exist_ok=True)
