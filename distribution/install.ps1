[CmdletBinding()]
param([string]$InstallRoot, [string]$RhinoPath, [string]$CodexConfig, [switch]$ReplaceUpstream, [switch]$ChangeManagementService)
& (Join-Path $PSScriptRoot 'bootstrap.ps1') -Action install @PSBoundParameters
