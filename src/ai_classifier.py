"""AI importance classifier + summarizer.

Supports any OpenAI-compatible chat-completions API (OpenAI, DeepSeek, Groq,
Ollama, etc.) and Anthropic Messages API. The user supplies the API key.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import requests

from .config import AIConfig
from .email_client import EmailMessage

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an email triage assistant.
Given an email and the user's importance criteria, decide if the email is IMPORTANT.

Return STRICT JSON only, no markdown fences, with this schema:
{
  "important": true or false,
  "confidence": 0.0 to 1.0,
  "reason": "one short sentence",
  "summary": "2-4 sentence summary in the user's language if important, else empty string",
  "action_needed": "what the user should do next, or empty string"
}

Rules:
- Follow the user's importance criteria exactly.
- When uncertain, lean toward important=false for pure noise, but true if a real person needs something.
- Never invent facts not present in the email.
- Summary must be self-contained and actionable.
"""


@dataclass
class Classification:
    important: bool
    confidence: float
    reason: str
    summary: str
    action_needed: str
    raw: str = ""


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n…[truncated]"


def _parse_classification(content: str) -> Classification:
    """Parse model output; tolerate markdown fences and minor schema drift."""
    text = content.strip()
    # Strip ```json ... ```
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", text)
    if fence:
        text = fence.group(1).strip()

    # Find the first JSON object
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        text = match.group(0)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Last resort: keyword scan
        lowered = content.lower()
        important = any(
            w in lowered for w in ("important", "true", "yes", "urgent", "需要", "重要")
        )
        return Classification(
            important=important,
            confidence=0.3,
            reason="Model returned unparseable output; heuristic fallback.",
            summary="",
            action_needed="",
            raw=content,
        )

    important = bool(data.get("important", False))
    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    return Classification(
        important=important,
        confidence=confidence,
        reason=str(data.get("reason", "") or ""),
        summary=str(data.get("summary", "") or ""),
        action_needed=str(data.get("action_needed", "") or ""),
        raw=content,
    )


class AIClassifier:
    def __init__(self, cfg: AIConfig) -> None:
        self.cfg = cfg

    def classify(self, mail: EmailMessage, criteria: str) -> Classification:
        user_prompt = self._build_prompt(mail, criteria)
        provider = (self.cfg.provider or "openai").lower()

        if provider == "anthropic" and self.cfg.anthropic_api_key:
            content = self._call_anthropic(user_prompt)
        else:
            content = self._call_openai_compatible(user_prompt)

        result = _parse_classification(content)
        log.info(
            "AI → important=%s conf=%.2f | %s | %s",
            result.important,
            result.confidence,
            mail.subject[:80],
            result.reason[:120],
        )
        return result

    def _build_prompt(self, mail: EmailMessage, criteria: str) -> str:
        body = _truncate(mail.body or "", self.cfg.max_body_chars)
        return (
            f"USER IMPORTANCE CRITERIA:\n{criteria}\n\n"
            f"EMAIL\n"
            f"Account: {mail.account}\n"
            f"From: {mail.sender}\n"
            f"To: {mail.to}\n"
            f"Date: {mail.date}\n"
            f"Subject: {mail.subject}\n\n"
            f"Body:\n{body}\n\n"
            f"Decide if this email is important per the criteria. Return JSON only."
        )

    # ---- OpenAI-compatible ----

    def _call_openai_compatible(self, user_prompt: str) -> str:
        api_key = self.cfg.api_key
        if not api_key:
            raise RuntimeError(
                "AI_API_KEY is missing. Put it in .env (or export it) before running."
            )

        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }

        # Some OpenAI-compatible servers do not support response_format
        for attempt in (1, 2):
            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.cfg.timeout_seconds,
                )
            except requests.RequestException as exc:
                raise RuntimeError(f"AI request failed: {exc}") from exc

            if resp.status_code == 400 and "response_format" in payload and attempt == 1:
                payload.pop("response_format", None)
                continue

            if resp.status_code >= 400:
                raise RuntimeError(
                    f"AI API error {resp.status_code}: {resp.text[:500]}"
                )

            data = resp.json()
            try:
                return data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError) as exc:
                raise RuntimeError(f"Unexpected AI response shape: {data}") from exc

        raise RuntimeError("AI request failed after retry.")

    # ---- Anthropic ----

    def _call_anthropic(self, user_prompt: str) -> str:
        api_key = self.cfg.anthropic_api_key
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.cfg.anthropic_model,
            "max_tokens": 800,
            "temperature": 0.1,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        try:
            resp = requests.post(
                url, headers=headers, json=payload, timeout=self.cfg.timeout_seconds
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Anthropic request failed: {exc}") from exc

        if resp.status_code >= 400:
            raise RuntimeError(f"Anthropic API error {resp.status_code}: {resp.text[:500]}")

        data = resp.json()
        try:
            parts = data.get("content") or []
            return "".join(p.get("text", "") for p in parts if p.get("type") == "text")
        except (KeyError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Anthropic response: {data}") from exc
