# Orbital Predictor and Visibility MCP Server

This project answers one practical question:

Can I see a satellite from my location right now?

It uses live orbital data and astronomy calculations to return a clear yes or no, plus supporting details like direction and angle in the sky.

## Demo

- Orbital Predictor and Visibility MCP Server Demo: [https://youtu.be/jTxCydAicmk](https://youtu.be/jTxCydAicmk)

## What It Does (Simple View)

When you provide a satellite ID and your location, the server:

1. Downloads the latest orbit data (TLE) from CelesTrak.
2. Calculates where Earth, the Sun, and the satellite are right now.
3. Computes the satellite direction from you (azimuth and elevation).
4. Marks the satellite as visible only if:
   - It is above your minimum elevation threshold.
   - It is sunlit.

## Why This Is Useful

- For skywatching: quickly check if a target like ISS might be visible.
- For operations: use consistent programmatic visibility checks in other systems.
- For diagnostics: detailed logs explain each calculation step.

## Technical Highlights

- MCP server framework: `fastmcp`
- Input/output models: `pydantic`
- Orbital computations: `skyfield`
- Live TLE data fetch: `requests` from CelesTrak
- Satellite ID support: 1 to 9 alphanumeric characters (future-proofed beyond older 5-digit assumptions)

## Logging

The project writes logs to a dedicated log file path configured in `.env`.

- Log path key: `LOG_FILE_PATH`
- Example value: `logs/orbital_predictor_mcp.log`

## MCP Inspector

You can inspect and test this MCP server with MCP Inspector.

There are two valid ways to run it, depending on your goal.

### Approach 1: Inspector + Stdio Server (Recommended for Local Tool Testing)

Use this when you want Inspector to launch and manage the MCP server process directly.

Script shortcut:

```powershell
.\run_mcp_inspector.ps1
```

Manual equivalent:

```powershell
$env:MCP_TRANSPORT="stdio"
.\.venv\Scripts\fastmcp.exe dev inspector orbital_mcp_server.py:mcp
```

Notes:
- In this mode, the MCP server uses stdio and does not bind to a TCP port.
- The script already forces `MCP_TRANSPORT=stdio` for this launch.
- If Inspector UI auto-remembers a previous HTTP target, switch transport to `stdio` in the UI.
- The script always uses inspector default ports: UI `6274`, proxy `6277`.
- Before launch, it checks these ports and stops any existing listener process, then logs what it stopped.

### Approach 2: Standalone Server (Streamable HTTP) + Inspector as Separate Client

Use this when you want the MCP server running independently and Inspector connecting to it over HTTP.

Step 1: start the MCP server (Terminal A):

```powershell
.\.venv\Scripts\python.exe .\orbital_mcp_server.py
```

With current `.env`, this serves MCP at:

```text
http://127.0.0.1:8001/mcp
```

Step 2: start Inspector and connect to that endpoint (Terminal B):

```powershell
npx -y @modelcontextprotocol/inspector --transport http --server-url http://127.0.0.1:8001/mcp
```

Script shortcut for Terminal B:

```powershell
.\run_mcp_inspector_http.ps1
```

Notes:
- In this mode, server and inspector are separate processes on separate ports.
- This is useful for integration testing with a long-running server.
- Standalone inspector CLI uses its own default UI/proxy ports.
- The HTTP inspector script also enforces default ports (`6274`/`6277`) and clears conflicting listeners before launch.
- `MCP_SERVER_URL` is optional. If not set, the script builds URL from `.env` keys: `MCP_HOST`, `MCP_PORT`, and `MCP_PATH`.

Option 1 (script):

```powershell
.\run_mcp_inspector.ps1
```

Option 2 (direct command):

```powershell
$env:MCP_TRANSPORT="stdio"
.\.venv\Scripts\fastmcp.exe dev inspector orbital_mcp_server.py:mcp
```

Inspector starts a local UI so you can list tools and invoke `predict_satellite_visibility` interactively.
This command starts both the inspector and your MCP server process together.

## What Is the .bsp File?

`de421.bsp` is a planetary ephemeris file from JPL/NASA.

- It contains precise precomputed positions for solar-system bodies over a time range.
- This project uses it to determine Sun/Earth geometry, which is required for the satellite `is_sunlit` check.
- Without this file, visibility results would be incomplete or wrong because sunlit status cannot be computed correctly.

### Is It Static?

- For a given version (for example `de421.bsp`), yes, the file content is static.
- Over time, newer ephemeris versions may be published (for different ranges/precision), so you may choose to upgrade intentionally.
- This server now supports startup auto-download when the file is missing.

### Startup Auto-Fetch Behavior

At startup, the server checks `SKYFIELD_EPHEMERIS_FILE`.

- If the file exists, it is reused.
- If missing and `EPHEMERIS_AUTO_DOWNLOAD=true`, it downloads from `EPHEMERIS_DOWNLOAD_URL`.
- If missing and auto-download is disabled, startup fails with a clear error.

## Setup

1. Ensure `.env` exists (it is included in this project).
2. Install dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run

```powershell
.\.venv\Scripts\python.exe orbital_mcp_server.py
```

## Configuration Keys

All runtime settings are loaded from `.env`.

- `CELESTRAK_URL_TEMPLATE`
- `TLE_REQUEST_TIMEOUT_SECONDS`
- `SKYFIELD_EPHEMERIS_FILE`
- `EPHEMERIS_AUTO_DOWNLOAD`
- `EPHEMERIS_DOWNLOAD_URL`
- `MCP_SERVER_NAME`
- `MCP_TRANSPORT`
- `MCP_HOST`
- `MCP_PORT`
- `MCP_PATH`
- `LOG_LEVEL`
- `LOG_FORMAT`
- `LOG_FILE_PATH`

### Port Configuration

Set these keys in `.env`:

- `MCP_TRANSPORT=streamable-http` (or `http`/`sse`/`stdio`)
- `MCP_HOST=127.0.0.1`
- `MCP_PORT=8001`
- `MCP_PATH=/mcp`

When transport is `stdio`, there is no TCP port. The server now logs this explicitly at startup.
When transport is HTTP-based (`http`, `sse`, `streamable-http`), startup logs include host, port, and path.

## MCP Tool

- `predict_satellite_visibility`

### Input

- `satellite_id`: string, 1 to 9 alphanumeric
- `latitude_deg`: float
- `longitude_deg`: float
- `elevation_m`: float, optional
- `minimum_visible_elevation_deg`: float, optional

### Output

- `is_visible`: true/false
- `visibility_reason`: human-readable reason
- `azimuth_deg`, `elevation_deg`, `distance_km`
- `is_sunlit`
- metadata (`satellite_name`, TLE epoch info)
