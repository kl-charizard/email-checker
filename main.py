#!/usr/bin/env python3
"""Email Auto Checker — CLI entry point.

Examples:
  python main.py check          # one pass
  python main.py watch          # run forever (cron/systemd friendly)
  python main.py status         # show memory stats
  python main.py history        # recent decisions
  python main.py test-telegram  # send a test Telegram message
  python main.py test-ai        # classify a sample email with your AI key
"""

from __future__ import annotations

import argparse
import logging
import sys
import warnings
from pathlib import Path

# Keep every runtime artifact inside this project folder
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# macOS system Python may use LibreSSL; harmless warning from urllib3
warnings.filterwarnings("ignore")
warnings.filterwarnings("default", category=DeprecationWarning)
warnings.filterwarnings("default", category=RuntimeWarning)

from src.config import ensure_runtime_dirs, load_config  # noqa: E402
from src.checker import EmailChecker  # noqa: E402
from src.memory import MemoryStore  # noqa: E402
from src.telegram_notifier import TelegramNotifier  # noqa: E402
from src.ai_classifier import AIClassifier  # noqa: E402
from src.email_client import EmailMessage  # noqa: E402


def setup_logging(level: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(path, encoding="utf-8"),
        ],
    )


def cmd_check(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    ensure_runtime_dirs(cfg)
    setup_logging(cfg.log_level, cfg.log_path)
    checker = EmailChecker(cfg)
    counters = checker.run_once()
    print(
        f"Done. fetched={counters['fetched']} "
        f"important={counters['important']} "
        f"notified={counters['notified']} "
        f"errors={counters['errors']}"
    )
    return 0 if counters["errors"] == 0 else 1


def cmd_watch(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    ensure_runtime_dirs(cfg)
    setup_logging(cfg.log_level, cfg.log_path)
    checker = EmailChecker(cfg)
    checker.run_forever(once=False)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    ensure_runtime_dirs(cfg)
    mem = MemoryStore(cfg.memory_path, cfg.max_decisions)
    stats = mem.stats()
    print("Email Checker status")
    print(f"  config:           {cfg.memory_path}")
    print(f"  interval:         {cfg.check_interval_seconds}s")
    print(f"  accounts:         {', '.join(a.name + ('*' if a.enabled else '(off)') for a in cfg.accounts) or '(none)'}")
    print(f"  AI provider:      {cfg.ai.provider} / {cfg.ai.model}")
    print(f"  Telegram:         {'configured' if cfg.telegram.bot_token and cfg.telegram.chat_id else 'NOT configured'}")
    print(f"  total_checked:    {stats.get('total_checked', 0)}")
    print(f"  total_important:  {stats.get('total_important', 0)}")
    print(f"  total_notified:   {stats.get('total_notified', 0)}")
    print(f"  total_errors:     {stats.get('total_errors', 0)}")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    mem = MemoryStore(cfg.memory_path, cfg.max_decisions)
    rows = mem.recent_decisions(limit=args.limit, important_only=args.important_only)
    if not rows:
        print("No decisions recorded yet.")
        return 0
    for r in rows:
        flag = "⭐" if r.get("important") else "  "
        print(f"{flag} [{r.get('account')}] {r.get('subject', '')[:70]}")
        print(f"     from={r.get('from', '')[:50]}  at={r.get('checked_at', '')}")
        if r.get("reason"):
            print(f"     reason: {r.get('reason')}")
        if r.get("summary"):
            print(f"     summary: {r.get('summary')[:200]}")
        print()
    return 0


def cmd_test_telegram(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    tg = TelegramNotifier(cfg.telegram)
    ok = tg.send("✅ <b>Email checker</b> Telegram test message — this is working!")
    print("Telegram test:", "OK" if ok else "FAILED (check TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
    return 0 if ok else 1


def cmd_test_ai(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    clf = AIClassifier(cfg.ai)
    sample = EmailMessage(
        uid="test-1",
        message_id="<test-1@example.com>",
        subject=args.subject or "Invoice #4821 due in 3 days",
        sender="billing@example-corp.com",
        to="you@example.com",
        date="Mon, 06 Jan 2025 10:00:00 +0000",
        body=(
            "Hi,\n\nThis is a reminder that invoice #4821 for $1,240.00 is due on Friday. "
            "Please process payment to avoid late fees.\n\nThanks,\nAccounting"
        ),
        account="test",
    )
    result = clf.classify(sample, cfg.importance_criteria)
    print(f"important:     {result.important}")
    print(f"confidence:    {result.confidence}")
    print(f"reason:        {result.reason}")
    print(f"summary:       {result.summary}")
    print(f"action_needed: {result.action_needed}")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    mem = MemoryStore(cfg.memory_path, cfg.max_decisions)
    n = mem.clear_processed(args.account)
    mem.save()
    print(f"Cleared processed markers ({n} entries){f' for {args.account}' if args.account else ''}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="email-checker",
        description="AI email triage for Gmail/Outlook with Telegram summaries.",
    )
    p.add_argument(
        "--config",
        default="config.json",
        help="Path to config.json (default: config.json in project root)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="Run one check pass").set_defaults(func=cmd_check)
    sub.add_parser("watch", help="Run forever on the configured interval").set_defaults(func=cmd_watch)
    sub.add_parser("status", help="Show runtime status and memory stats").set_defaults(func=cmd_status)

    hist = sub.add_parser("history", help="Show recent AI decisions")
    hist.add_argument("--limit", type=int, default=20)
    hist.add_argument("--important-only", action="store_true")
    hist.set_defaults(func=cmd_history)

    sub.add_parser("test-telegram", help="Send a Telegram test message").set_defaults(func=cmd_test_telegram)

    t_ai = sub.add_parser("test-ai", help="Classify a sample email with your AI key")
    t_ai.add_argument("--subject", default=None)
    t_ai.set_defaults(func=cmd_test_ai)

    reset = sub.add_parser("reset", help="Clear processed markers (re-check mail)")
    reset.add_argument("--account", default=None, help="Only clear one account")
    reset.set_defaults(func=cmd_reset)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
