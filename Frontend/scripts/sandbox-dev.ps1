param(
  [string]$BindHost = '127.0.0.1',
  [int]$Port = 4173
)

$ErrorActionPreference = 'Stop'

$buildScript = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'sandbox-build.ps1'
& $buildScript -BindHost $BindHost -Port $Port -Serve -Watch
