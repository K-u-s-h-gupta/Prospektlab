param(
    [string]$AccessToken = "",
    [string]$ProjectRef = "",
    [string]$DbPassword = "",
    [string]$DbUrl = "",
    [switch]$IncludeAll,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$supabaseDir = Join-Path $repoRoot "supabase"

if (-not (Test-Path -LiteralPath $supabaseDir)) {
    throw "Supabase CLI project was not initialized. Run 'npx supabase init' first."
}

$supabaseCmd = "npx.cmd"

function Invoke-Supabase {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $supabaseCmd supabase @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Supabase CLI command failed: supabase $($Arguments -join ' ')"
    }
}

if ($AccessToken) {
    $env:SUPABASE_ACCESS_TOKEN = $AccessToken
}

$pushArgs = @("db", "push")
if ($IncludeAll) {
    $pushArgs += "--include-all"
}
if ($DryRun) {
    $pushArgs += "--dry-run"
}

if ($DbUrl) {
    $pushArgs += @("--db-url", $DbUrl)
    Invoke-Supabase -Arguments $pushArgs
    exit 0
}

if (-not $AccessToken) {
    throw "Provide -AccessToken for linked-project pushes, or use -DbUrl for direct database pushes."
}

if (-not $ProjectRef) {
    throw "Provide -ProjectRef for linked-project pushes, or use -DbUrl for direct database pushes."
}

$linkArgs = @("link", "--project-ref", $ProjectRef)
if ($DbPassword) {
    $linkArgs += @("--password", $DbPassword)
}

Invoke-Supabase -Arguments $linkArgs
$linkedPushArgs = @($pushArgs) + "--linked"
Invoke-Supabase -Arguments $linkedPushArgs
