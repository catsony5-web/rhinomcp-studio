[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('install','doctor','uninstall')][string]$Action,
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'RhinoMCPStudio'),
    [string]$RhinoPath,
    [string]$CodexConfig,
    [switch]$ReplaceUpstream,
    [switch]$ChangeManagementService
)
$ErrorActionPreference = 'Stop'
$studioRoot = [IO.Path]::GetFullPath($InstallRoot)
$studioMarker = Join-Path $studioRoot '.rhinomcp-studio-root'
$studioMarkerText = "RhinoMCP Studio managed installation`n"
if ($studioRoot.TrimEnd('\') -eq [IO.Path]::GetPathRoot($studioRoot).TrimEnd('\') -or
    $studioRoot.TrimEnd('\') -eq [Environment]::GetFolderPath('UserProfile').TrimEnd('\')) {
    throw "Unsafe installation directory: $studioRoot"
}
$studioAncestor = [IO.DirectoryInfo]$studioRoot
while ($null -ne $studioAncestor) {
    if ($studioAncestor.Exists -and ($studioAncestor.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Installation directory cannot use a junction/symlink: $($studioAncestor.FullName)"
    }
    $studioAncestor = $studioAncestor.Parent
}
if ((Test-Path -LiteralPath $studioRoot) -and (Get-ChildItem -LiteralPath $studioRoot -Force | Select-Object -First 1)) {
    if (!(Test-Path -LiteralPath $studioMarker) -or [IO.File]::ReadAllText($studioMarker) -ne $studioMarkerText) {
        throw "Refusing a directory not owned by RhinoMCP Studio: $studioRoot"
    }
}
$studioUv = Join-Path $studioRoot 'bootstrap\uv.exe'
$studioVersion = '0.11.28'
$studioPythonVersion = '3.12.12'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $studioRoot 'runtime'
$env:UV_CACHE_DIR = Join-Path $studioRoot 'cache'
$env:UV_NO_CONFIG = '1'
$env:PYTHONUTF8 = '1'
if ($Action -eq 'install') {
    if ([Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne 'X64') {
        throw 'This Windows release supports x64. macOS Intel and Apple Silicon use install.sh.'
    }
    New-Item -ItemType Directory -Path $studioRoot -Force | Out-Null
    [IO.File]::WriteAllText($studioMarker, $studioMarkerText)
    if (!(Test-Path -LiteralPath $studioUv)) {
        $studioBootstrap = Join-Path $studioRoot 'bootstrap'
        New-Item -ItemType Directory -Path $studioBootstrap -Force | Out-Null
        $studioArchive = Join-Path $studioBootstrap 'uv.zip'
        $studioAsset = "https://github.com/astral-sh/uv/releases/download/$studioVersion/uv-x86_64-pc-windows-msvc.zip"
        Invoke-WebRequest -Uri $studioAsset -OutFile $studioArchive
        # Published SHA-256 for the pinned Astral uv 0.11.28 release asset.
        $studioChecksum = '0a23463216d09c6a72ff80ef5dc5a795f07dc1575cb84d24596c2f124a441b7b'
        if ((Get-FileHash -LiteralPath $studioArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $studioChecksum.ToLowerInvariant()) {
            throw 'uv download checksum mismatch.'
        }
        Expand-Archive -LiteralPath $studioArchive -DestinationPath $studioBootstrap -Force
        Remove-Item -LiteralPath $studioArchive
    }
    if ((& $studioUv --version) -notmatch "^uv $([regex]::Escape($studioVersion))(?:\s|$)") {
        throw "Unexpected private uv version. Expected $studioVersion."
    }
    & $studioUv python install $studioPythonVersion --no-bin --no-registry
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the private Python runtime.' }
} elseif (!(Test-Path -LiteralPath $studioUv)) {
    throw 'The private installer runtime was not found. Run install.ps1 to repair this installation.'
}
$studioPython = & $studioUv python find --no-project --managed-python --no-python-downloads $studioPythonVersion
if ($LASTEXITCODE -ne 0) { throw 'Private Python is unavailable. Rerun install.ps1 to repair it.' }
$studioArguments = @((Join-Path $PSScriptRoot 'manager.py'), $Action, '--install-root', $studioRoot, '--uv', $studioUv, '--bundle', $PSScriptRoot)
if ($RhinoPath) { $studioArguments += @('--rhino-path', $RhinoPath) }
if ($CodexConfig) { $studioArguments += @('--codex-config', $CodexConfig) }
if ($ReplaceUpstream) { $studioArguments += '--replace-upstream' }
if ($ChangeManagementService) { $studioArguments += '--change-management-service' }
& $studioPython @studioArguments
if ($LASTEXITCODE -ne 0) { throw "RhinoMCP Studio $Action did not complete. See the diagnostic above." }
if ($Action -eq 'uninstall') {
    # Python has exited. Revalidate the exact absolute target before recursive removal.
    $studioResolved = (Resolve-Path -LiteralPath $studioRoot).ProviderPath
    if ($studioResolved.TrimEnd('\') -ne $studioRoot.TrimEnd('\') -or
        [IO.File]::ReadAllText($studioMarker) -ne $studioMarkerText -or
        (Test-Path -LiteralPath (Join-Path $studioRoot 'state.json'))) {
        throw 'Cleanup target changed; private runtime was preserved.'
    }
    Remove-Item -LiteralPath $studioRoot -Recurse -Force
    Write-Output 'RhinoMCP Studio private files removed.'
}
