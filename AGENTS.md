# AGENTS.md

## Purpose
This repository hosts a FastMCP server that predicts real-time satellite visibility from a ground observer.

Primary references:
- [README.md](README.md)
- [PromptValidation/UserPromptValidation.md](PromptValidation/UserPromptValidation.md)

## Project Layout
- `orbital_mcp_server.py`: single-server implementation (config, validation, TLE fetch, visibility math, MCP tool).
- `requirements.txt`: Python dependencies.
- `run_mcp_inspector.ps1`: launches FastMCP inspector in stdio mode.
- `run_mcp_inspector_http.ps1`: launches inspector as HTTP client against a separately running server.
- `de421.bsp`: ephemeris file used for Sun/Earth geometry.

## Environment And Setup
Expected local environment:
- Windows PowerShell
- Local virtual environment at `.venv`
- Runtime config in `.env`

Install dependencies:
- `./.venv/Scripts/python.exe -m pip install -r requirements.txt`

## Run And Validate
Run server directly:
- `./.venv/Scripts/python.exe orbital_mcp_server.py`

Inspector (stdio, server launched by inspector):
- `./run_mcp_inspector.ps1`

Inspector (HTTP client mode, server already running):
- Start server first, then run `./run_mcp_inspector_http.ps1`

There is no dedicated automated test suite in this repo yet. Use inspector-based smoke testing for behavior checks.

## Behavior That Must Stay Intact
- The MCP tool name is `predict_satellite_visibility`.
- `satellite_id` validation allows 1-9 alphanumeric characters and is normalized to uppercase.
- Visibility is true only when:
  - elevation is strictly greater than the requested threshold, and
  - satellite is sunlit.
- Ephemeris startup behavior:
  - reuse file if present,
  - auto-download when missing only if enabled by config,
  - fail fast with clear error when missing and auto-download is disabled.

## Editing Guidelines
- Prefer minimal, targeted edits in `orbital_mcp_server.py`; avoid broad refactors.
- Keep pydantic constraints and explicit error types (`TLEFetchError`, `TLEParseError`) unless a task explicitly changes API behavior.
- Preserve detailed logging around fetch, parse, ephemeris loading, and visibility computation.
- If changing transport or startup flow, preserve both stdio and HTTP modes and keep script compatibility.

## Documentation Practice
- Link to existing docs instead of copying long explanations:
  - [README.md](README.md)
  - [PromptValidation/UserPromptValidation.md](PromptValidation/UserPromptValidation.md)