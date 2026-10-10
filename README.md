# Email Auto Checker

AI-powered email triage for **Gmail** and **Outlook**.

It checks your inbox on a schedule, uses an AI model (your API key) to decide which messages matter based on **your** criteria, stores a JSON memory of what it saw, and sends a short Telegram summary for every important email.

Works on **Raspberry Pi (Linux)**, **macOS**, and **Windows**.  
All runtime data (venv, caches, logs, memory) stays **inside this project folder**.

---

## Table of contents

1. [What it does](#what-it-does)
2. [Requirements](#requirements)
3. [Install](#install)
4. [Get your API keys](#get-your-api-keys)
5. [Configure](#configure)
6. [First run](#first-run)
7. [Daily use (CLI)](#daily-use-cli)
8. [How importance is decided](#how-importance-is-decided)
9. [Memory file (JSON)](#memory-file-json)
10. [Run on Raspberry Pi (systemd)](#run-on-raspberry-pi-systemd)
11. [Run on macOS / Windows](#run-on-macos--windows)
12. [Project layout](#project-layout)
13. [Security notes](#security-notes)
14. [Troubleshooting](#troubleshooting)

---

## What it does

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐     ┌──────────────┐
│ Gmail /     │────▶│ AI classifier│────▶│ JSON memory     │────▶│ Telegram     │
│ Outlook     │     │ (your prompt │     │ data/memory.json│     │ bot summary  │
│ (IMAP, read │     │  + your key) │     │ (dedup only)    │     │ (if important│
│  only)      │     └──────────────┘     └─────────────────┘     └──────────────┘
└─────────────┘
  mail stays unread
```

| Feature | Detail |
|---|---|
| Email sources | Gmail and Outlook (IMAP, app passwords) |
| AI judgment | Free-text importance rules written by you |
| AI providers | OpenAI-compatible (OpenAI, DeepSeek, Groq, Ollama, …) or Anthropic |
| Alerts | Telegram bot message with summary + suggested action |
| Memory | Human-readable JSON of processed mail and decisions |
| Mail flags | **Never marks mail as read** — stays `\Unseen` for you |
| Privacy | Keys stay in local `.env`; nothing cached outside the folder |

---

## Requirements

- **Python 3.9 or newer** (`python3 --version`)
- A **Gmail** and/or **Outlook** account with IMAP access
- An **AI API key** (OpenAI, DeepSeek, Groq, Anthropic, or a local Ollama server)
- A **Telegram bot** (free, created with @BotFather)
- On Raspberry Pi: Raspberry Pi OS (or any Debian/Ubuntu-like Linux) with network access

---

## Install

### Linux / Raspberry Pi / macOS

```bash
git clone https://github.com/kl-charizard/email-checker.git
cd email-checker
chmod +x setup.sh run.sh
./setup.sh
```

`setup.sh` will:

1. Create a virtual environment in `.venv/`
2. Install dependencies into that venv
3. Copy `.env.example` → `.env` and `config.example.json` → `config.json`
4. Create `data/` and `logs/`

### Windows (PowerShell)

```powershell
git clone https://github.com/kl-charizard/email-checker.git
cd email-checker
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
copy config.example.json config.json
```

Then run commands with `python main.py ...` instead of `./run.sh ...`.

---

## Get your API keys

You need four things filled into `.env`. Do this once.

### 1. AI API key

**Option A — OpenAI**

1. Open https://platform.openai.com/api-keys
2. Create a key (starts with `sk-`)
3. Put it in `.env` as `AI_API_KEY`
4. Keep `AI_BASE_URL=https://api.openai.com/v1` and pick a model (e.g. `gpt-4o-mini`)

**Option B — DeepSeek / Groq / other OpenAI-compatible**

Same as OpenAI, but change `AI_BASE_URL` to that provider’s API base URL and set `AI_MODEL` to one of their model names.

**Option C — Anthropic (Claude)**

1. Get a key from https://console.anthropic.com/
2. Set `AI_PROVIDER=anthropic`
3. Set `ANTHROPIC_API_KEY=sk-ant-...`
4. Optionally set `ANTHROPIC_MODEL=claude-3-5-haiku-latest`

**Option D — local Ollama (free, offline)**

1. Install [Ollama](https://ollama.com/) and run a model (`ollama pull llama3.1`)
2. Set:

```ini
AI_API_KEY=ollama
AI_BASE_URL=http://127.0.0.1:11434/v1
AI_MODEL=llama3.1
```

### 2. Telegram bot

1. In Telegram, open **[@BotFather](https://t.me/BotFather)**
2. Send `/newbot`, choose a display name and a username ending in `bot`
3. Copy the **token** → `TELEGRAM_BOT_TOKEN=123456789:ABC...`
4. Open **[@userinfobot](https://t.me/userinfobot)** (or @RawDataBot) and copy your **chat id** → `TELEGRAM_CHAT_ID=...`
5. In Telegram, send any message to **your new bot** once (so it is allowed to reply)

### 3. Gmail app password

1. Go to https://myaccount.google.com/security
2. Enable **2-Step Verification** if not already on
3. Open **App passwords** (or https://myaccount.google.com/apppasswords)
4. Create one named `email-checker`
5. Copy the 16-character password (spaces ok) → `GMAIL_APP_PASSWORD=`

> Your normal Google password will **not** work over IMAP. Use the app password only.

### 4. Outlook app password

**Personal @outlook.com / @hotmail.com / @live.com**

1. Go to https://account.live.com/proofs/AppPassword
2. Create an app password → `OUTLOOK_APP_PASSWORD=`

**Work / school (Microsoft 365)**

Many tenants disable IMAP passwords entirely and require OAuth2 (not automated in this tool). If login fails with *Basic authentication is disabled*, use Gmail for that inbox, or a mailbox that still accepts app passwords.

---

## Configure

Edit two files in the project root.

### `.env` — secrets (never commit)

```ini
# ---- AI ----
AI_API_KEY=sk-your-key
AI_BASE_URL=https://api.openai.com/v1
AI_MODEL=gpt-4o-mini

# ---- Telegram ----
TELEGRAM_BOT_TOKEN=123456789:ABCdef...
TELEGRAM_CHAT_ID=123456789

# ---- Gmail (optional) ----
GMAIL_ADDRESS=you@gmail.com
GMAIL_APP_PASSWORD=abcd efgh ijkl mnop

# ---- Outlook (optional) ----
OUTLOOK_ADDRESS=you@outlook.com
OUTLOOK_APP_PASSWORD=your-app-password
```

Use one provider or both. Leave unused ones empty/disabled.

On Linux/macOS lock the file:

```bash
chmod 600 .env
```

### `config.json` — behavior (safe to share)

```json
{
  "check_interval_seconds": 300,
  "max_emails_per_check": 25,
  "days_lookback": 7,
  "importance_criteria": "Mark as important only if: (1) a human needs a reply or decision from me, (2) money, billing, security, or account access is involved, (3) a deadline is within 7 days, or (4) it is from someone I regularly work with and action is required. Ignore marketing, newsletters, automated notifications that need no action, and social media unless there is a direct request.",
  "accounts": [
    { "name": "gmail", "provider": "gmail", "enabled": true },
    { "name": "outlook", "provider": "outlook", "enabled": true }
  ],
  "folders": ["INBOX"],
  "telegram": { "enabled": true, "send_non_important_digest": false }
}
```

| Field | Meaning | Default |
|---|---|---|
| `check_interval_seconds` | How often `watch` checks for new mail | `300` (5 min) |
| `max_emails_per_check` | Cap of unseen messages per pass | `25` |
| `days_lookback` | Only consider mail newer than N days | `7` |
| `importance_criteria` | The **user prompt** the AI follows | see above |
| `accounts[].enabled` | Turn Gmail/Outlook on or off | `true` |
| `folders` | IMAP folders to scan | `["INBOX"]` |
| `telegram.send_non_important_digest` | Also message non-important reasons | `false` |

Disable an account you are not using:

```json
{ "name": "outlook", "provider": "outlook", "enabled": false }
```

---

## First run

Always test the pieces before leaving it running.

```bash
# 1. Confirm Python + config load
./run.sh status

# 2. Confirm Telegram works (you should get a message on your phone)
./run.sh test-telegram

# 3. Confirm AI key works (classifies a sample invoice email)
./run.sh test-ai

# 4. One real inbox pass
./run.sh check
```

If `test-telegram` and `test-ai` both succeed, you are ready.

---

## Daily use (CLI)

On Linux/macOS use `./run.sh <command>`. On Windows use `python main.py <command>`.

| Command | What it does |
|---|---|
| `check` | Scan inboxes once, classify, notify, save memory |
| `watch` | Loop forever using `check_interval_seconds` |
| `status` | Show accounts, AI model, Telegram, and memory stats |
| `history` | List recent AI decisions |
| `history --important-only` | Only important ones |
| `history --limit 50` | Show more |
| `test-telegram` | Send a test Telegram message |
| `test-ai` | Classify a sample email with your AI setup |
| `reset` | Forget processed IDs (will re-read old mail) |
| `reset --account gmail` | Reset only one account |
| `--help` | Full command help |

Examples:

```bash
./run.sh check
./run.sh history --important-only
./run.sh watch
```

`watch` is what you leave running on a server / Raspberry Pi.

---

## How importance is decided

You write the rules in `config.json` → `importance_criteria`. The AI reads **only** that prompt plus the email (subject, from, date, body text up to 6000 characters) and returns:

```json
{
  "important": true,
  "confidence": 0.9,
  "reason": "Invoice due in 3 days",
  "summary": "Billing asks for payment of invoice #4821 ($1,240) before Friday...",
  "action_needed": "Pay invoice or confirm with finance"
}
```

- **Important** → Telegram alert with summary + action
- **Not important** → only written to JSON memory (unless digest is enabled)

**Read-only inbox:** the checker fetches with `BODY.PEEK[]` and never sets the `\Seen` flag. Your Gmail/Outlook messages stay unread after triage. Re-checks are avoided via `data/memory.json`, not by marking mail as read.

Write criteria in English or Chinese. Be specific. Examples of good criteria:

```text
Important if:
- Someone asks me a direct question or expects a reply
- Money, invoices, billing, refunds, or security alerts
- A deadline within 7 days
- From my manager, team, or known clients
Not important:
- Marketing, newsletters, receipts under $50
- Automated CI/CD or monitoring spam with no action
- Social media notifications
```

After editing `importance_criteria`, the next `check`/`watch` pass uses it immediately (no restart needed for `check`; restart `watch` if it is already running).

---

## Memory file (JSON)

Everything the tool learned lives in `data/memory.json`:

```json
{
  "version": 1,
  "processed": {
    "gmail": { "18302": "2025-01-06T12:00:00+00:00" }
  },
  "decisions": [
    {
      "account": "gmail",
      "uid": "18302",
      "from": "billing@example.com",
      "subject": "Invoice #4821 due in 3 days",
      "important": true,
      "reason": "Payment deadline inside 7 days",
      "summary": "Invoice #4821 for $1,240 is due Friday...",
      "notified": true,
      "checked_at": "2025-01-06T12:00:00+00:00"
    }
  ],
  "stats": {
    "total_checked": 128,
    "total_important": 17,
    "total_notified": 17,
    "total_errors": 0
  }
}
```

- **`processed`** — UIDs / Message-IDs already handled (prevents duplicates)
- **`decisions`** — every classification (capped at `max_decisions`, default 2000)
- **`stats`** — counters shown by `status`

You can back this file up, diff it, or import it into another tool.

Logs go to `logs/checker.log`.

---

## Run on Raspberry Pi (systemd)

After `./setup.sh` and a successful `./run.sh check`:

```bash
# Adjust paths in the unit if your user/folder differ
sudo cp deploy/email-checker.service /etc/systemd/system/
sudo nano /etc/systemd/system/email-checker.service   # set User= and paths

sudo systemctl daemon-reload
sudo systemctl enable --now email-checker

# Watch it
systemctl status email-checker
journalctl -u email-checker -f
```

Default unit assumes:

- User: `pi`
- Folder: `/home/pi/email-checker`
- Starts: `.venv/bin/python main.py watch`

To stop: `sudo systemctl stop email-checker`

---

## Run on macOS / Windows

**macOS** — same as Linux. To run in the background without systemd:

```bash
./run.sh watch >> logs/watch.out 2>&1 &
```

Or use `launchd` / a scheduled `cron` job:

```cron
*/5 * * * * cd /path/to/email-checker && ./run.sh check >> logs/cron.log 2>&1
```

**Windows** — use Task Scheduler:

- Program: `C:\path\to\email-checker\.venv\Scripts\python.exe`
- Arguments: `main.py watch`
- Start in: `C:\path\to\email-checker`

Or run in a terminal: `python main.py watch`

---

## Project layout

```
email-checker/
├── main.py                  # CLI entry point
├── setup.sh                 # create venv + install deps
├── run.sh                   # run CLI with project-local caches
├── requirements.txt
├── config.example.json      # copy → config.json
├── .env.example             # copy → .env (secrets)
├── src/
│   ├── config.py            # load config + env
│   ├── email_client.py      # IMAP for Gmail/Outlook
│   ├── ai_classifier.py     # importance + summary
│   ├── telegram_notifier.py # Telegram messages
│   ├── memory.py            # JSON memory store
│   └── checker.py           # main loop
├── deploy/
│   └── email-checker.service  # systemd unit
├── tests/
│   └── test_core.py         # quick self-tests
├── data/                    # memory.json (runtime, gitignored)
└── logs/                    # checker.log (runtime, gitignored)
```

**Nothing is written outside this folder.** `run.sh` forces `PIP_CACHE_DIR`, `PYTHONPYCACHEPREFIX`, and `TMPDIR` into the project (`.pip-cache/`, `.pycache/`, `.tmp/`).

---

## Security notes

- Never commit `.env` or `config.json` if you put secrets there (both are in `.gitignore`).
- Prefer **app passwords**, not your primary mailbox password.
- Email **bodies** are sent to your AI provider so it can judge importance — use a local Ollama model if you want fully private processing.
- Attachments are **not** uploaded.
- Telegram receives only the summary of messages marked important (unless you enable the non-important digest).
- Tokens in `.env` are only used against your configured AI URL and `api.telegram.org`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `python3 not found` | Install Python 3.9+ (`sudo apt install python3 python3-venv` on Pi) |
| `AI_API_KEY is missing` | Put the key in `.env`, then re-run |
| `test-ai` fails with 401 | Wrong key or wrong `AI_BASE_URL` |
| `test-ai` unparseable / weird JSON | Try a stronger model, or simplify criteria |
| Telegram not arriving | Run `test-telegram`; check token/chat id; message the bot once |
| Gmail: `AUTHENTICATIONFAILED` | Use an **App Password**, not your Google password |
| Outlook: `Basic authentication is disabled` | Personal account needs App Password; work accounts may need OAuth2 (not supported) — use Gmail for those |
| `connection refused` on Ollama | Start Ollama: `ollama serve` |
| Same emails re-checked | Do not delete `data/memory.json`; use `reset` only on purpose |
| Want to re-read old mail | `./run.sh reset` then `./run.sh check` |
| Logs not visible | `tail -f logs/checker.log` |
| SSL / LibreSSL warning on old macOS | Harmless; install a newer Python from python.org if it bothers you |

Self-test the core (no network needed):

```bash
.venv/bin/python tests/test_core.py
```

---

## License

Use and modify freely for personal or commercial projects. No warranty — this tool can send email content to your chosen AI provider; review `importance_criteria` and provider policies before use.
