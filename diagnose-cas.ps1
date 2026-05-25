# Quick PowerShell diagnostic for CDSL eCAS
# Usage: .\diagnose-cas.ps1 -PdfPath "C:\path\to\your.pdf" -Password "your_password"
param(
    [Parameter(Mandatory=$true)]
    [string]$PdfPath,
    [Parameter(Mandatory=$true)]
    [string]$Password
)

$python = "D:\PROSPEKTLAB\.venv-prospektlab311b\Scripts\python.exe"
$script = "D:\PROSPEKTLAB\finagent\debug_cas.py"

if (-not (Test-Path $PdfPath)) {
    Write-Host "File not found: $PdfPath" -ForegroundColor Red
    exit 1
}

& $python $script $PdfPath $Password 2>&1
