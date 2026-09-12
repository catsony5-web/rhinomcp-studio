[CmdletBinding()]
param([string]$InstallRoot)
& (Join-Path $PSScriptRoot 'bootstrap.ps1') -Action doctor @PSBoundParameters
