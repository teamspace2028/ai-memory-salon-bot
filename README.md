# 💇 AI Bot with Memory

Telegram AI assistant for a hair salon with **short-term** and **long-term memory**, real appointment booking, and optional Google Calendar sync.

Built with **aiogram 3**, **OpenAI** (via [ProxyAPI](https://proxyapi.ru) or direct API), **ChromaDB** (RAG), and **SQLite**.

This project extends the booking-focused idea with a combined memory architecture: conversational context + document/knowledge retrieval in one bot.

---

## 📋 Table of contents

- [Features](#-features)
- [Memory architecture](#-memory-architecture-core)
- [How it works](#-how-it-works)
- [Tech stack](#-tech-stack)
- [Project structure](#-project-structure)
- [Installation](#-installation)
- [API keys](#-api-keys)
- [Configuration (.env)](#-configuration-env)
- [Run](#-run)
- [Usage](#-usage)
- [Admin notifications](#-admin-notifications)
- [Google Calendar](#-google-calendar-optional)
- [Customize for your salon](#-customize-for-your-salon)
- [Data storage](#-data-storage)
- [Troubleshooting](#-troubleshooting)
- [Ideas for next steps](#-ideas-for-next-steps)

---

## ✨ Features

- **Natural dialogue** in Russian powered by an LLM (OpenAI-compatible API).
- **Combined memory** (short + long) — see [Memory architecture](#-memory-architecture-core).
- **Salon knowledge base** (services, prices, hours, booking rules) as a text file + RAG.
- **Appointment booking** with checks for:
  - opening hours (default 10:00–20:00);
  - lunch break (13:00–14:00);
  - slot conflicts;
  - past datetimes (cannot book in the past).
- **Function calling / tools**: `get_available_slots`, `create_booking`, `get_my_bookings`, `cancel_booking`.
- **Photo / Vision**: send a haircut reference photo — the bot describes the style and suggests a service.
- **UI buttons**: reply keyboard + inline service pick + cancel booking.
- **Admin alerts** for new bookings and cancellations (`ADMIN_ACCOUNTS`).
- **Google Calendar sync** (optional): create/delete events with bookings.
- **Timezone-aware** scheduling (default `Asia/Yekaterinburg`).
- **SQLite** persistence for bookings and client profiles.

---

## 🧠 Memory architecture (core)

The bot is designed around **three memory modes**, all active together in the main app:

### 1. Short-term memory (conversation buffer)

- Stores the **last N messages** per Telegram user in RAM (`dict[user_id → deque]`).
- Default **N = 10** (`HISTORY_LIMIT` in `.env`).
- Every LLM reply includes this recent dialogue history.
- Cleared with `/reset` or `/clear_short` (or process restart — it is in-memory only).

**Use case:** “What did I just ask?”, follow-ups, name mentioned a few turns ago.

### 2. Long-term memory (documents → embeddings → Chroma)

- User uploads **PDF / TXT / DOCX**.
- Text is chunked (~500 characters with overlap), embedded, and stored in **ChromaDB** (`./memory`).
- On each question, the bot retrieves the most relevant chunks (RAG) and passes them to the model.
- Shared salon instruction file `knowledge_base/salon_strijka.txt` is indexed at startup into a shared collection.
- User documents are per-user collections; clear with `/clear_long`.

**Use case:** Q&A over a price list, policy PDF, or any uploaded document — answers grounded in retrieved text.

### 3. Combined memory (default production mode)

On every user message the bot builds a prompt from:

1. System instruction + live salon data (hours, services, client profile).
2. **Short-term** dialogue history.
3. **Long-term** RAG context (shared KB + optional user document).
4. Tools for real booking / cancel actions.

So the assistant can chat naturally **and** use uploaded / knowledge-base data in the same conversation.

| Mode | Storage | Lifetime | Command helpers |
|------|---------|----------|-----------------|
| Short-term | RAM deque | Until reset / restart | `/reset`, `/status` |
| Long-term | Chroma (`./memory`) | Persistent on disk | upload file, `/clear_long` |
| Combined | Both | — | `/status`, `/clear` |

Educational standalone scripts live in `examples/` (`bot_short_memory.py`, `bot_long_memory.py`).

---

## ⚙️ How it works

```
Client ──▶ Telegram ──▶ app/handlers ──▶ services/chat + ai_assistant
                              │                    │
                              │         OpenAI / ProxyAPI
                              │         (chat + tools + vision)
                              │                    │
                              │         short memory (RAM)
                              │         long memory (Chroma RAG)
                              │                    │
                              │         services/booking ──▶ SQLite
                              │                    │
                              │              Google Calendar (optional)
                              │
                              └──▶ admin notifications
```

1. User sends text, a photo, or a document in Telegram.
2. Handlers route the update (menu / booking callbacks / docs / free chat).
3. `ai_assistant` loads short history + retrieves long-term context.
4. The model may call tools (`get_available_slots`, `create_booking`, `cancel_booking`, …).
5. Booking layer writes SQLite (and Google Calendar if enabled).
6. Final answer is sent to the user; admins get alerts when configured.

---

## 🧰 Tech stack

- **Python 3.11+**
- [aiogram 3](https://docs.aiogram.dev/) — Telegram Bot API
- [OpenAI Python SDK](https://github.com/openai/openai-python) — Chat Completions + tools (+ Vision)
- [ProxyAPI](https://proxyapi.ru) — optional OpenAI-compatible proxy (default in `.env.example`)
- [ChromaDB](https://www.trychroma.com/) — vector store for long-term memory
- **SQLite** — bookings & client profiles
- [python-dotenv](https://github.com/theskumar/python-dotenv)
- Optional: Google Calendar API (`google-api-python-client`, `google-auth-oauthlib`)

---

## 📁 Project structure

```text
app/
  __main__.py              # entrypoint (python -m app)
  config.py                # env settings
  salon_data.py            # structured services / hours / contacts
  handlers/                # Telegram routers (start, bookings, docs, chat)
  keyboards/               # reply + inline keyboards
  services/
    ai_assistant.py        # LLM, tools, short memory
    long_memory.py         # Chroma RAG, document ingest
    booking.py             # slots, create/cancel booking
    google_calendar.py     # optional calendar sync
    chat.py / notify.py    # LLM wrapper + admin alerts
  db/
    repository.py          # SQLite access
knowledge_base/
  salon_strijka.txt        # salon instruction + FAQ (indexed for RAG)
examples/                  # standalone short / long memory demos
bot.py                     # thin launcher: python bot.py
requirements.txt
.env.example
```

---

## 🚀 Installation

```bash
git clone https://github.com/nifontovoleg/strizhka-ai-memory-bot.git
cd strizhka-ai-memory-bot

python -m venv .venv

# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# Linux / macOS:
# source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # Windows: copy .env.example .env
```

Fill in secrets in `.env` (see below), then run the bot.

---

## 🔑 API keys

### Telegram bot token

1. Open [@BotFather](https://t.me/BotFather).
2. Create a bot with `/newbot`.
3. Copy the token into `BOT_TOKEN`.

### LLM key (ProxyAPI recommended)

1. Sign up at [proxyapi.ru](https://proxyapi.ru).
2. Create an API key.
3. Put it in `PROXYAPI_API_KEY` (or `OPENAI_API_KEY`).

Default base URL:

```text
https://api.proxyapi.ru/openai/v1
```

To use official OpenAI instead: set `PROXYAPI_ENABLED=false` and provide a normal OpenAI key.

---

## 🔧 Configuration (.env)

```env
BOT_TOKEN=123456:ABC...

PROXYAPI_ENABLED=true
PROXYAPI_API_KEY=your_proxyapi_key
PROXYAPI_BASE_URL=https://api.proxyapi.ru/openai/v1
OPENAI_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

SALON_TIMEZONE=Asia/Yekaterinburg
ADMIN_ACCOUNTS=@your_admin,123456789

HISTORY_LIMIT=10
DB_PATH=bookings.db
MEMORY_DIR=./memory
KNOWLEDGE_FILE=./knowledge_base/salon_strijka.txt

GOOGLE_CALENDAR_ENABLED=false
GOOGLE_CREDENTIALS_FILE=credentials.json
GOOGLE_TOKEN_FILE=token.json
GOOGLE_CALENDAR_ID=primary
```

| Variable | Required | Description |
|----------|:--------:|-------------|
| `BOT_TOKEN` | ✅ | Telegram bot token |
| `PROXYAPI_API_KEY` / `OPENAI_API_KEY` | ✅ | LLM + embeddings key |
| `PROXYAPI_ENABLED` | ❌ | Use ProxyAPI base URL (default `true`) |
| `OPENAI_MODEL` | ❌ | Chat model (default `gpt-4o-mini`) |
| `OPENAI_EMBEDDING_MODEL` | ❌ | Embedding model for Chroma |
| `HISTORY_LIMIT` | ❌ | Short-term memory size (default `10`) |
| `SALON_TIMEZONE` | ❌ | IANA timezone for slots / calendar |
| `ADMIN_ACCOUNTS` | ❌ | `@username` and/or chat ids for alerts |
| `GOOGLE_CALENDAR_ENABLED` | ❌ | Sync bookings to Google Calendar |

> **Security:** never commit `.env`, `credentials.json`, or `token.json`. They are listed in `.gitignore`.

---

## ▶️ Run

```bash
python bot.py
# or
python -m app
```

On startup you should see logs about knowledge-base indexing (Chroma) and polling for your bot username.

Check memory status in Telegram with `/status`.

---

## 💬 Usage

### Commands

| Command | Action |
|---------|--------|
| `/start` | Greeting + main menu |
| `/help` | Short help |
| `/mybookings` | List upcoming bookings (cancel button) |
| `/status` | Short memory size, doc chunks, KB chunks, LLM endpoint, GCal |
| `/reset` / `/clear_short` | Clear short-term dialogue memory |
| `/clear_long` | Clear user’s uploaded documents from Chroma |
| `/clear` | Clear short memory + user docs (salon KB stays) |

### Menu buttons

- Services & prices  
- Working hours  
- Book appointment  
- My bookings  
- Address & contacts  

### Memory demos

1. **Short-term:** say your name, continue chatting, ask “what’s my name?”.
2. **Long-term:** upload a TXT/PDF, ask questions about its content.
3. **Combined:** keep chatting while referring to the uploaded file / salon KB.
4. **Vision:** send a haircut photo (optionally with a caption).

### Example booking dialogue

```text
Client: Book me a men’s haircut tomorrow at 15:00. Name Oleg, phone +79001234567
Bot:    (calls create_booking) Booking confirmed for …
```

Cancellation must go through `cancel_booking` (or the inline cancel button) so SQLite and Google Calendar stay in sync.

---

## 🔔 Admin notifications

Set in `.env`:

```env
ADMIN_ACCOUNTS=@your_admin,5921878055
```

- Admins listed by `@username` must press `/start` once so the bot can store `chat_id`.
- Alerts are sent in the **admin’s private chat with the bot**, not into the client dialogue.
- If an admin books themselves, that chat is excluded from the duplicate alert.

---

## 📆 Google Calendar (optional)

1. Google Cloud Console → enable **Google Calendar API**.
2. Create OAuth client (**Desktop app**) → download `credentials.json` into the project root.
3. OAuth consent screen: **External** + add your Gmail as a **Test user** (avoid `403: org_internal`).
4. Set `GOOGLE_CALENDAR_ENABLED=true`.
5. Restart the bot and create a test booking — browser OAuth once → `token.json` is saved.

Use `SALON_TIMEZONE` matching your salon (e.g. `Asia/Yekaterinburg`) so event times are correct.

---

## 🛠 Customize for your salon

- **Services / prices / duration / hours:** `app/salon_data.py`
- **Behaviour, FAQ, scripts:** `knowledge_base/salon_strijka.txt` (re-indexed on bot start)
- **Timezone / admins / memory size:** `.env`

---

## 🗄 Data storage

| Location | Contents |
|----------|----------|
| `bookings.db` | Bookings, known users, client profiles |
| `./memory/` | Chroma persistent vector store (long-term memory) |
| RAM short memory | Last `HISTORY_LIMIT` messages per user |
| `token.json` | Google OAuth token (if Calendar enabled) |

---

## ❓ Troubleshooting

- **`409 Conflict: only one bot instance`** — stop extra `python bot.py` processes.
- **Bot says it can’t see photos** — restart after updating; photo handler uses Vision.
- **Says “cancelled” but event remains** — cancellation must use the tool/button; restart latest code.
- **Wrong calendar time** — set `SALON_TIMEZONE` to your real zone; restart.
- **`403: org_internal` on Google login** — Consent screen must be **External** + Test users.
- **Embeddings / chat 503 via ProxyAPI** — transient; retry; check ProxyAPI balance/status.
- **Admins get no alerts** — check `ADMIN_ACCOUNTS` and that `@username` pressed `/start`.

---

## 🌱 Ideas for next steps

- SMS / Telegram reminders before visits  
- Multiple stylists with separate calendars  
- Reschedule tool (change time without cancel+create)  
- Persistent short-term memory in SQLite/Redis  
- Webhook deployment + Docker  

---

> Educational / portfolio project. Salon data is demo-oriented — replace with your business details before production use.
