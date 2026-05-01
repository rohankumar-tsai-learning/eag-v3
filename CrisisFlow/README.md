# CrisisFlow Command Center

CrisisFlow is a browser-based crisis command center with a local MCP server and reactive UI for monitoring May 2026 energy and food volatility.

## Demo

- YouTube demo: [https://youtu.be/Gjf2SfdPuww](https://youtu.be/Gjf2SfdPuww)

## Features

- Local MCP server exposed over Streamable HTTP at `/mcp`
- Seven MCP tools:
  - `health_status_tool`
  - `chat_prompt_tool`
  - `get_watchlist_tool`
  - `set_watchlist_tool`
  - `market_probe_tool`
  - `vault_manager_tool`
  - `ui_dispatch_tool`
- Prompt-driven watchlist configuration in `data/watchlist.json`
- Time-series vault persistence in `data/crisis_vault.json`
- Live dashboard with Risk Matrix, Trends, Advisory Wizard, and audit tail
- Server-sent event updates for dashboard and audit stream
- 4-hour local freshness guard and 60-second Gemini cooldown
- Gemini-backed enrichment and crude-oil spot lookup with fallback behavior
- Local file-backed knowledge base for future requests using vault, watchlist, and audit history

## Supported Watchlist Targets

- `jkm_lng_asia`
- `crude_oil_india`
- `wheat_futures`
- `rice_futures`
- `urea_cf`
- `npk_mosaic`

## Architecture

### Frontend

The browser frontend uses **Prefab** as the state management layer:

- **`public/prefab-state.js`**: Prefab-based store with reactive subscribers
- **`public/prefab-renderers.js`**: Pure rendering functions (risk, advisory, trends, audit)
- **`public/prefab-app.js`**: Orchestration layer handling network integration and event delegation

The frontend communicates with the backend exclusively through:
- `POST /api/dispatch` - Run market probe and get advisory
- `GET /api/vault` - Fetch commodity time-series
- `GET /api/ui/stream` - SSE for real-time payload updates
- `GET /api/audit/stream` - SSE for audit log tail
- `DELETE /api/audit/log` - Clear audit log

### Backend
- **`src/index.ts`**: Entry point for web server
- **`src/mcp.ts`**: Entry point for MCP server
- **`src/services/marketProbeService.ts`**: Live market data fetching
- **`src/services/uiDispatchService.ts`**: Payload building and broadcasting
- **`src/services/riskService.ts`**: Risk matrix calculation
- **`src/services/geminiAdvisoryService.ts`**: Gemini-backed advisory enrichment
- **`src/services/vaultService.ts`**: Time-series persistence
- **`src/services/auditLogger.ts`**: Operation logging

## Quick start

```bash
npm install
```

Start the web runtime:

```bash
npm run dev
```

Start the MCP runtime in a second terminal:

```bash
npm run dev:mcp
```

Open the dashboard at `http://localhost:8080` unless `PORT` is overridden in `.env`.

VS Code MCP client config is already scaffolded in `.vscode/mcp.json` for `http://127.0.0.1:8181/mcp`.

## Environment

Copy `.env.example` to `.env` and set:

- `PORT` (optional, defaults to `8080`)
- `MCP_PORT` (optional, defaults to `8181`)
- `GEMINI_API_KEY` (optional)

Without a Gemini key, the platform still operates using direct-source, vault, seeded-baseline, and cooldown fallback paths.

## Local Knowledge Base

The project keeps a local file-backed knowledge base for future requests:

- `data/crisis_vault.json` stores historical commodity values, sources, timestamps, and sentiment context
- `data/watchlist.json` stores the active monitoring scope
- `logs/session_audit.log` stores operational history and tool activity

This is persistent operational memory, not a full conversational memory system.

## Prompt-Driven Usage

If your chat client supports MCP tool orchestration, you can issue natural-language requests such as:

- `We're in the middle of the May 2026 supply crisis. Run a full live market probe, store the results, and push them to the dashboard. Then tell me which commodity has moved the most and whether the situation is getting worse.`
- `Focus on energy and wheat, refresh the dashboard now, and summarize the biggest move.`

The MCP server can either expose atomic tools for the chat client to orchestrate directly or use `chat_prompt_tool` as a natural-language fallback entrypoint.

## End-To-End Flow

VS Code Chat LLM
→ discovers MCP tools from the local MCP server
→ chooses tool calls from a natural-language prompt
→ optionally checks `health_status_tool`
→ optionally reads or updates watchlist state
→ runs `market_probe_tool` for live market fetching
→ performs internet/API lookups and limited Gemini enrichment where needed
→ writes operational state to local files
→ packages results through `ui_dispatch_tool`
→ updates the Prefab-style dashboard via SSE
→ preserves future context in vault, watchlist, and audit files
