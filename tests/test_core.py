"""Quick self-tests for core pieces. Run: python tests/test_core.py"""

from __future__ import annotations

import json
import sys
import tempfile
from email.message import EmailMessage as MimeMessage
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.memory import MemoryStore
from src.email_client import _extract_body, _html_to_text
from src.ai_classifier import _parse_classification


def test_memory() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "memory.json"
        mem = MemoryStore(path, max_decisions=5)
        assert not mem.is_processed("gmail", "1")
        mem.mark_processed("gmail", "1")
        assert mem.is_processed("gmail", "1")
        assert not mem.is_processed("outlook", "1")

        for i in range(7):
            mem.add_decision(
                account="gmail",
                uid=str(i),
                message_id=f"<{i}@x>",
                sender="a@b.c",
                subject=f"S{i}",
                date="Mon, 06 Jan 2025 10:00:00 +0000",
                important=(i % 2 == 0),
                reason="r",
                summary="s",
            )
        mem.save()
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["decisions"]) == 5  # trimmed to max
        assert data["stats"]["total_checked"] == 7
        assert data["stats"]["total_important"] == 4

        mem2 = MemoryStore(path)
        assert mem2.is_processed("gmail", "1")
        assert mem2.stats()["total_checked"] == 7
        print("✓ memory store")


def test_html_to_text() -> None:
    html = "<html><style>.x{}</style><p>Hello <b>world</b></p><script>x=1</script>&amp; more</p>"
    text = _html_to_text(html)
    assert "Hello" in text and "world" in text
    assert "x=1" not in text
    assert ".x{}" not in text
    assert "& more" in text
    print("✓ html to text")


def test_extract_body_plain() -> None:
    msg = MimeMessage()
    msg["Subject"] = "Hi"
    msg.set_content("Plain body here.")
    assert "Plain body here." in _extract_body(msg)
    print("✓ extract plain body")


def test_parse_classification() -> None:
    raw = '```json\n{"important": true, "confidence": 0.9, "reason": "deadline", "summary": "Pay invoice", "action_needed": "Pay by Fri"}\n```'
    c = _parse_classification(raw)
    assert c.important is True
    assert abs(c.confidence - 0.9) < 1e-6
    assert c.summary == "Pay invoice"
    assert c.action_needed == "Pay by Fri"

    c2 = _parse_classification("this is not json but important: true")
    assert c2.important is True  # heuristic fallback
    print("✓ parse classification")


if __name__ == "__main__":
    test_memory()
    test_html_to_text()
    test_extract_body_plain()
    test_parse_classification()
    print("\nAll core tests passed.")
