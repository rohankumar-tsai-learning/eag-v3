# Gandalf the Organizer

> *"A wizard is never late, nor is he early — he arrives precisely when he means to."*

**Gandalf the Organizer** is a Chrome extension that lives in your browser's side panel and acts as an intelligent daily briefing assistant. Powered by Google Gemini and backed by a FastAPI server, it autonomously runs an AI agent loop that gathers real-time weather, AI stock data, and the latest AI news — then streams its reasoning and results directly to you, live in the browser.

This is a personal learning project built to explore AI agent design, streaming backends, and Chrome extension development from scratch.

---

## What It Does

When you click **Run the Organiser**, Gandalf:

1. Opens a thinking panel and begins its agent loop on the backend.
2. Calls a series of tools — weather, stocks, news — using **LLM-guided reasoning** (no hardcoded logic).
3. Summarises each module with Gemini and streams the results to the side panel in real time via **Server-Sent Events (SSE)**.
4. Renders weather conditions, AI stock tickers, and a live AI news feed, all in one place.
5. Enforces a 30-minute refresh cooldown after a successful run to avoid unnecessary API usage.

The agent decides *which tool to call and when* — it reads its own reasoning logs and picks the next action. This is a minimal but real implementation of a **ReAct-style AI agent loop**.

---

## Feature Overview

| Feature | Description |
|---|---|
| Weather | Current conditions via Open-Meteo + reverse geocoding from browser geolocation |
| AI Stocks | Live price data for AI-related tickers |
| AI News | Recent AI news fetched and surfaced in a readable feed |
| Task Creation | Create and manage to-dos via backend todo APIs |
| Event Reminder Emails | Schedule events and send email reminders (default: 15 minutes before event) |
| Thinking Panel | Real-time stream of the agent's thoughts, tool calls, and observations |
| Todo & Scheduling | Lightweight helpers for managing tasks and email scheduling |

---

## Tech Stack

### Frontend — Chrome Extension (Manifest V3)

- **UI:** HTML, CSS, vanilla JavaScript
- **Side Panel API:** `chrome.sidePanel` (MV3)
- **Storage:** `chrome.storage.local`
- **Streaming:** `EventSource` (SSE from backend)
- **Geolocation:** `navigator.geolocation` with manifest permission

### Backend — Python

- **Framework:** FastAPI with streaming response support
- **Agent:** Custom ReAct-style loop in `backend/app/agent/agent_loop.py`
- **LLM:** Google Gemini via `google.generativeai` SDK
- **Tools:**
  - `get_weather.py` — Open-Meteo forecast + reverse geocoding
  - `get_ai_stocks.py` — Live stock quote pipeline
  - `search_ai_news.py` — AI news search and retrieval
  - `todo_manager.py` — Task list management
        - `schedule_email.py` — Event reminder email scheduling helper (supports `reminder_minutes_before`, default `15`)

---

## High-Level Architecture

```
[Chrome Extension Side Panel]
        |
        |  EventSource (SSE)
        v
[FastAPI Backend]
        |
        |  Agent Loop (Gemini LLM reasoning)
        v
[Tools: Weather | Stocks | News | Todos]
```

1. User opens the side panel and clicks **Run the Organiser**.
2. Frontend opens an SSE connection to `/api/agent/run`.
3. Backend starts the agent loop — Gemini reasons, picks a tool, observes results, repeats.
4. Each module result (weather, stocks, news) is packaged as a grouped payload and streamed back.
5. Frontend renders each payload as it arrives, updating sections progressively.

---

## Local Development

### Requirements

- Python 3.10+
- A [Google Gemini API key](https://aistudio.google.com/app/apikey)
- Chrome browser

### Backend Setup

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux
pip install -r requirements.txt
```

Create a `backend/.env` file:

```env
GEMINI_API_KEY=your_key_here
BACKEND_HOST=localhost
BACKEND_PORT=8000
DEBUG=True
EMAIL_SENDER=your_gmail_address
EMAIL_PASSWORD=your_app_password
```

`EMAIL_SENDER` and `EMAIL_PASSWORD` are required to enable event reminder emails.

Start the server:

```bash
python main.py
```

Or use the provided scripts: `START_SERVER.bat` (Windows) / `START_SERVER.sh` (macOS/Linux).

### Extension Setup

1. Open `chrome://extensions` in Chrome.
2. Enable **Developer mode** (top-right toggle).
3. Click **Load unpacked**.
4. Select the `extension/` folder from this repo.
5. Pin the extension and open the side panel.

---

## API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Server health check |
| `/api/agent/run` | GET | Starts agent loop; streams SSE events |
| `/api/todos` | GET | Fetch all to-do items |
| `/api/todos` | POST | Create a new to-do item |
| `/api/todos/{todo_id}` | PUT | Update a to-do item |
| `/api/todos/{todo_id}` | DELETE | Delete a to-do item |
| `/api/todos/{todo_id}/complete` | PUT | Mark a to-do item as complete |
| `/api/events/schedule` | POST | Schedule an event reminder email |
| `/api/events/scheduled` | GET | List scheduled event reminders |

**Query parameters for `/api/agent/run`:**

| Parameter | Type | Description |
|---|---|---|
| `task` | string | Optional task prompt override |
| `city` | string | City name for weather fallback |
| `latitude` | float | Browser geolocation latitude |
| `longitude` | float | Browser geolocation longitude |
| `email` | string | Email for scheduling features |
| `max_iterations` | int | Max agent loop steps (default: 10) |

**Body for `POST /api/todos`:**

| Field | Type | Required | Description |
|---|---|---|---|
| `title` | string | Yes | Task title |
| `description` | string | Yes | Task details (tool enforces max length) |
| `due_date` | string | Yes | ISO datetime/date string |
| `importance` | string | No | `low`, `medium`, or `high` (default: `medium`) |

**Body for `POST /api/events/schedule`:**

| Field | Type | Required | Description |
|---|---|---|---|
| `event_title` | string | Yes | Event name |
| `event_time` | string | Yes | Event time in ISO format |
| `event_description` | string | Yes | Event details |
| `recipient_email` | string | Yes | Reminder recipient |
| `reminder_minutes_before` | int | No | Minutes before event (default: `15`) |

---

## Project Status

This is an active learning project. Features may change as I explore more of the AI agent and browser extension space. Contributions, suggestions, and feedback are welcome.

- Demo: [https://www.youtube.com/watch?v=uJNQudI3i4c](https://www.youtube.com/watch?v=uJNQudI3i4c)

## Current Behavior Rules

- Weather and stocks receive LLM summaries.
- News is data-only (no LLM summary).
- Cooldown messaging is emitted once per wait period.
- Weather location prefers browser coordinates and resolved city name.

## Troubleshooting

- If backend import fails, run with the configured venv interpreter.
- If weather shows generic location text, confirm geolocation permission is granted in Chrome.
- If side panel does not auto-run, ensure popup successfully sets AUTO_RUN_ON_PANEL_OPEN.
