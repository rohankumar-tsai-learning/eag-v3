Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Clear-PortListener {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $listeners) {
        Write-Output "Port $Port is free."
        return
    }

    $owningProcessIds = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($owningProcessId in $owningProcessIds) {
        try {
            $proc = Get-Process -Id $owningProcessId -ErrorAction Stop
            Write-Output "Port $Port is in use by $($proc.ProcessName) (PID=$owningProcessId). Stopping process..."
            Stop-Process -Id $owningProcessId -Force -ErrorAction Stop
            Write-Output "Stopped $($proc.ProcessName) (PID=$owningProcessId) on port $Port."
        }
        catch {
            Write-Output "Could not stop process PID=$owningProcessId on port ${Port}: $($_.Exception.Message)"
        }
    }
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$fastMcpExe = Join-Path $projectRoot ".venv\Scripts\fastmcp.exe"

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found at $pythonExe"
}

if (-not (Test-Path $fastMcpExe)) {
    throw "fastmcp executable not found at $fastMcpExe"
}

Write-Output "Starting MCP Inspector for Orbital Predictor server..."
Write-Output "This command launches both inspector and MCP server via FastMCP dev mode."
Write-Output "Inspector URL will be shown in terminal output."

# Inspector expects a stdio server process. Force stdio for this launch only.
$env:MCP_TRANSPORT = "stdio"
Clear-PortListener -Port 6274
Clear-PortListener -Port 6277

Write-Output "Using inspector default ports (UI: 6274, Proxy: 6277)."
Write-Output "In the Inspector UI, use stdio mode for this script."

& $fastMcpExe dev inspector orbital_mcp_server.py:mcp
