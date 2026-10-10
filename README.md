# Email Auto Checker

AI-powered email triage for **Gmail** and **Outlook**. It reads new mail, decides importance from *your* criteria, stores a JSON memory, and sends a Telegram summary of anything important.

Runs on **Raspberry Pi (Linux)**, **macOS**, and **Windows**. All runtime data stays inside this folder — venv, caches, logs, and memory.

## Features

| | |
|---|---|
| Gmail + Outlook | IMAP (app passwords) — no heavy SDKs |
| AI importance | OpenAI-compatible API (OpenAI, DeepSeek, Groq, Ollama…) or Anthropic |
| User criteria | Free-text prompt in `config.json` |
| Telegram | Instant alert + optional digest |
| Memory | JSON (`data/memory.json`) — processed IDs, decisions, stats |
| Portable | Python 3.10+, stdlib IMAP, tiny dependency list |

## Quick start

```bash
cd email-checker
./setup.sh                 # creates .venv, installs deps, copies config templates
# edit .env                # AI key, Telegram, email credentials
# edit config.json         # importance criteria, interval
./run.sh check             # one pass
./run.sh watch             # loop forever
```

On Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
copy config.example.json config.json
python main.py check
```

## Configuration

### `.env` (secrets — never commit)

```ini
AI_API_KEY=sk-...
AI_BASE_URL=https://api.openai.com/v1
AI_MODEL=gpt-4o-mini

TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=123456789

GMAIL_ADDRESS=you@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
OUTLOOK_ADDRESS=you@outlook.com
OUTLOOK_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

**Gmail app password** — Google Account → Security → 2-Step Verification → App passwords  
**Outlook app password** — https://account.live.com/proofs/AppPassword (personal @outlook.com/@hotmail.com with 2FA)  
**Telegram** — talk to [@BotFather](https://t.me/BotFather) for the token; [@userinfobot](https://t.me/userinfobot) for your chat id.

> **Outlook note:** Microsoft disables plain passwords on many accounts. If login returns *Basic authentication is disabled*, use an **App Password** on a personal account, or use Gmail for work/school Office 365 tenants (those often require OAuth2, which this tool does not automate).

### `config.json` (behavior)

```json
{
  "check_interval_seconds": 300,
  "importance_criteria": "Mark as important only if ..."
}
```

Edit `importance_criteria` in plain English (or Chinese). The AI follows it strictly.

## CLI

```bash
./run.sh check              # one pass
./run.sh watch              # daemon loop
./run.sh status             # stats + config summary
./run.sh history            # recent AI decisions
./run.sh history --important-only
./run.sh test-telegram      # verify bot token + chat id
./run.sh test-ai            # classify a sample invoice email
./run.sh reset              # re-process mail (forget processed IDs)
```

## Memory (JSON)

`data/memory.json` is human-readable and portable:

```json
{
  "processed": { "gmail": { "18302": "2025-01-06T12:00:00+00:00" } },
  "decisions": [
    {
      "account": "gmail",
      "subject": "Invoice #4821 due in 3 days",
      "important": true,
      "reason": "Payment deadline inside 7 days",
      "summary": "...",
      "notified": true
    }
  ],
  "stats": { "total_checked": 128, "total_important": 17 }
}
```

Back it up, diff it, or pipe it into another tool later.

## Raspberry Pi (systemd)

```bash
sudo cp deploy/email-checker.service /etc/systemd/system/
# edit User= and WorkingDirectory= / ExecStart= paths if needed
sudo systemctl daemon-reload
sudo systemctl enable --now email-checker
journalctl -u email-checker -f
```

## Cache / offline note

`run.sh` forces `PIP_CACHE_DIR`, `PYTHONPYCACHEPREFIX`, and `TMPDIR` into this project folder, so nothing is left behind in `$HOME` or `/tmp`. The `.gitignore` already excludes `.venv`, `.pip-cache`, `.tmp`, `.pycache`, `data/*`, and `logs/*`.

## Layout

```
email-checker/
├── main.py              # CLI entry
├── setup.sh / run.sh    # venv + run helpers
├── config.example.json  # behavior
├── .env.example         # secrets template
├── src/
│   ├── config.py        # load config + env
│   ├── email_client.py  # IMAP Gmail/Outlook
│   ├── ai_classifier.py # importance + summary
│   ├── telegram_notifier.py
│   ├── memory.py        # JSON memory
│   └── checker.py       # orchestration loop
├── deploy/email-checker.service
├── data/                # memory.json (runtime)
└── logs/                # checker.log (runtime)
```

## Security

- Keep `.env` private (`chmod 600 .env` on Linux/macOS).
- Prefer **app passwords** over your primary account password.
- The AI only sees email subject/body you fetch — no attachments are sent.
- API keys stay local; the tool never uploads them anywhere except your configured AI endpoint and Telegram.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `AI_API_KEY is missing` | Fill `AI_API_KEY` in `.env` |
| `Telegram … NOT configured` | Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` |
| Gmail login fails | Enable 2FA + create an **App Password** |
| Outlook login fails | Use app password; work tenants may need IMAP enabled |
| `response_format` error | Tool auto-retries without it for picky local models |
| Want to re-scan mail | `./run.sh reset` then `./run.sh check` |
