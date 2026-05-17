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

function Import-DotEnv {
	param(
		[Parameter(Mandatory = $true)]
		[string]$Path
	)

	$kv = @{}
	if (-not (Test-Path $Path)) {
		return $kv
	}

	foreach ($line in Get-Content $Path) {
		$trimmed = $line.Trim()
		if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.StartsWith("#")) {
			continue
		}

		$parts = $trimmed.Split("=", 2)
		if ($parts.Count -ne 2) {
			continue
		}

		$key = $parts[0].Trim()
		$value = $parts[1].Trim()
		$kv[$key] = $value
	}

	return $kv
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$dotEnv = Import-DotEnv -Path (Join-Path $projectRoot ".env")
$serverUrl = $null

if ($env:MCP_SERVER_URL) {
	$serverUrl = $env:MCP_SERVER_URL
}
elseif ($dotEnv.ContainsKey("MCP_HOST") -and $dotEnv.ContainsKey("MCP_PORT") -and $dotEnv.ContainsKey("MCP_PATH")) {
	$serverHost = $dotEnv["MCP_HOST"]
	$serverPort = $dotEnv["MCP_PORT"]
	$serverPath = $dotEnv["MCP_PATH"]
	if (-not $serverPath.StartsWith("/")) {
		$serverPath = "/$serverPath"
	}
	$serverUrl = "http://$serverHost`:$serverPort$serverPath"
}
else {
	$serverUrl = "http://127.0.0.1:8001/mcp"
}

Write-Output "Starting MCP Inspector in HTTP client mode..."
Write-Output "Target MCP URL: $serverUrl"
Write-Output "Make sure orbital_mcp_server.py is already running in streamable-http mode."
Clear-PortListener -Port 6274
Clear-PortListener -Port 6277
Write-Output "Using inspector default ports (UI: 6274, Proxy: 6277)."

npx -y @modelcontextprotocol/inspector --transport http --server-url $serverUrl
