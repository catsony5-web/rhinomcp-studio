[CmdletBinding()]
param(
    [string]$StateDirectory = (Join-Path (Split-Path -Parent $PSScriptRoot) '.build\management-owner\state'),
    [string]$PythonPath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'server\.venv\Scripts\python.exe'),
    [ValidateRange(1, 65535)]
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $StateDirectory -PathType Container)) {
    throw 'The initialized state directory does not exist. Initialize it separately before using this helper.'
}
$resolvedState = (Resolve-Path -LiteralPath $StateDirectory).ProviderPath
foreach ($requiredFile in @('control.sqlite3', 'signing-key.pem')) {
    if (-not (Test-Path -LiteralPath (Join-Path $resolvedState $requiredFile) -PathType Leaf)) {
        throw 'The state directory is not initialized. This helper does not create credentials or signing keys.'
    }
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw 'Python was not found. Supply the existing environment with -PythonPath.'
}
$resolvedPython = (Resolve-Path -LiteralPath $PythonPath).ProviderPath
$serviceScript = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'control_service.py')).ProviderPath
$serviceUrl = "http://127.0.0.1:$Port"
$adminUrl = "$serviceUrl/admin"

function Test-ManagementHealth {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "$serviceUrl/healthz" -TimeoutSec 2 -MaximumRedirection 0
        $health = $response.Content | ConvertFrom-Json
        return ($response.StatusCode -eq 200 -and $health.status -eq 'ok' -and $health.protocol -eq 1)
    }
    catch {
        return $false
    }
}

function Test-LocalListener {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $pending = $client.ConnectAsync('127.0.0.1', $Port)
        return ($pending.Wait(500) -and $client.Connected)
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function ConvertTo-QuotedPath {
    param([string]$Value)
    if ($Value.Contains('"')) {
        throw 'A filesystem path cannot contain a double quote.'
    }
    # Native Windows argument quoting: double trailing backslashes before the closing quote.
    return '"' + [regex]::Replace($Value, '(\\+)$', '$1$1') + '"'
}

if (Test-ManagementHealth) {
    Write-Output "Management service is already healthy. Admin URL: $adminUrl"
    return
}
if (Test-LocalListener) {
    throw "Port $Port is occupied but the expected health endpoint is unavailable. No process was stopped."
}

$logDirectory = Split-Path -Parent $resolvedState
$logSuffix = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$stdoutPath = Join-Path $logDirectory "local-management-$logSuffix.stdout.log"
$stderrPath = Join-Path $logDirectory "local-management-$logSuffix.stderr.log"
$processArguments = @(
    (ConvertTo-QuotedPath $serviceScript),
    '--state', (ConvertTo-QuotedPath $resolvedState),
    'serve', '--host', '127.0.0.1', '--port', $Port.ToString(), '--allow-insecure-loopback'
) -join ' '

$serviceProcess = Start-Process -FilePath $resolvedPython -ArgumentList $processArguments `
    -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath

$deadline = [DateTime]::UtcNow.AddSeconds(15)
while ([DateTime]::UtcNow -lt $deadline) {
    if (Test-ManagementHealth) {
        Write-Output "Management service is healthy. Admin URL: $adminUrl"
        return
    }
    $serviceProcess.Refresh()
    if ($serviceProcess.HasExited) {
        throw "Management service exited. Inspect its local error log: $stderrPath"
    }
    Start-Sleep -Milliseconds 250
}
throw "Management service has not become healthy yet. No process was stopped. Inspect its local error log: $stderrPath"
