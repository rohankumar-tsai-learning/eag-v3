# Gandalf the Organizer

Gandalf the Organizer is a Chrome side-panel assistant with a FastAPI backend and Gemini-powered reasoning.
It fetches weather, AI stocks, and AI news, then streams reasoning and grouped payloads to the UI in real time.

## What This Assistant Does

- Runs an agent loop from the extension side panel.
- Selects tools through LLM reasoning (no hardcoded response files).
- Processes modules in this cycle:
  1. Weather tool call -> LLM weather summary -> grouped payload to frontend
  2. Stocks tool call -> LLM stocks summary -> grouped payload to frontend
  3. News tool call -> data payload (no news summary)
- Applies a 60-second cooldown between summarized module cycles.
- Streams thought, tool, and observation messages to the frontend via SSE.
- Uses browser geolocation coordinates for local weather when available.

## Tech Stack

### Frontend (Chrome Extension, Manifest V3)

- Side panel UI: HTML/CSS/JavaScript
- Storage: chrome.storage.local
- Communication: EventSource streaming from backend
- Geolocation: navigator.geolocation with manifest geolocation permission

### Backend (Python)

- FastAPI for APIs and streaming endpoints
- Agent orchestration in backend/app/agent/agent_loop.py
- Tools:
  - Weather: Open-Meteo forecast + reverse geocoding
  - Stocks: Live quote fetch pipeline
  - AI News: AI news search/retrieval tool
  - Todos and scheduling utilities
- LLM: Gemini model via google.generativeai SDK

## High-Level Flow

1. User clicks Run the Organiser in popup.
2. Side panel opens and thinking panel is shown immediately.
3. Backend starts agent loop and emits streaming messages.
4. Frontend receives grouped module payloads and updates weather, stocks, and news sections.
5. Refresh is disabled for 30 minutes after successful run.

## Core Capabilities

- Real-time reasoning logs in the thinking panel
- Weather header + weather detail modal
- Stock ticker + stock detail modal
- AI news feed rendering
- Todo management and scheduling helpers

## Local Development

### Requirements

- Python 3.10+
- A Gemini API key
- Chrome (for loading unpacked extension)

### Backend Setup

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Create backend/.env and set values:

```env
GEMINI_API_KEY=your_key_here
BACKEND_HOST=localhost
BACKEND_PORT=8000
DEBUG=True
```

Run backend:

```bash
python main.py
```

### Extension Setup

1. Open chrome://extensions
2. Enable Developer mode
3. Click Load unpacked
4. Select the extension folder

## API Notes

- Health endpoint: /health
- Streaming agent endpoint: /api/agent/run
  - Supports task, city, latitude, longitude, email, max_iterations

## YouTube Demo Placeholders

- Technical Walkthrough: [https://youtu.be/uJNQudI3i4c](https://youtu.be/uJNQudI3i4c)

## Current Behavior Rules

- Weather and stocks receive LLM summaries.
- News is data-only (no LLM summary).
- Cooldown messaging is emitted once per wait period.
- Weather location prefers browser coordinates and resolved city name.

## Troubleshooting

- If backend import fails, run with the configured venv interpreter.
- If weather shows generic location text, confirm geolocation permission is granted in Chrome.
- If side panel does not auto-run, ensure popup successfully sets AUTO_RUN_ON_PANEL_OPEN.
