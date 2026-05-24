<#
.SYNOPSIS
    Check prerequisites for deploying TimesFM to Azure Container Apps.

.DESCRIPTION
    Verifies that Azure CLI, Docker, and HF_TOKEN are available.
    Provides direct install links and next-step guidance if anything is missing.
#>

param()

$ErrorActionPreference = "Stop"

function Test-Command($cmd) {
    $null = Get-Command $cmd -ErrorAction SilentlyContinue
    return $?
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  TimesFM Deployment - Prerequisites Check" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$allGood = $true

# ---------------------------------------------------------------------------
#  1. Docker
# ---------------------------------------------------------------------------
Write-Host "[1/3] Checking Docker ..." -NoNewline
if (Test-Command "docker") {
    $ver = docker --version 2>$null
    Write-Host "  OK  ($ver)" -ForegroundColor Green
} else {
    Write-Host "  MISSING" -ForegroundColor Red
    $allGood = $false
    Write-Host ""
    Write-Host "  Fix: Install Docker Desktop" -ForegroundColor Yellow
    Write-Host "  1. Download: https://www.docker.com/products/docker-desktop/"
    Write-Host "  2. Install and start Docker Desktop"
    Write-Host ""
}

# ---------------------------------------------------------------------------
#  2. Azure CLI
# ---------------------------------------------------------------------------
Write-Host "[2/3] Checking Azure CLI (az) ..." -NoNewline
if (Test-Command "az") {
    $ver = az --version 2>$null | Select-Object -First 1
    Write-Host "  OK  ($ver)" -ForegroundColor Green
} else {
    Write-Host "  MISSING" -ForegroundColor Red
    $allGood = $false
    Write-Host ""
    Write-Host "  Fix: Install Azure CLI" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Option A (Winget - easiest):" -ForegroundColor White
    Write-Host "    winget install Microsoft.AzureCLI"
    Write-Host ""
    Write-Host "  Option B (MSI direct download):" -ForegroundColor White
    Write-Host "    Invoke-WebRequest -Uri 'https://aka.ms/installazurecliwindowsx64' -OutFile (Join-Path $env:TEMP 'AzureCLI.msi')"
    Write-Host "    Start-Process msiexec.exe -Wait -ArgumentList '/I', (Join-Path $env:TEMP 'AzureCLI.msi'), '/quiet'"
    Write-Host ""
    Write-Host "  IMPORTANT: Restart PowerShell after installing." -ForegroundColor Yellow
    Write-Host ""
}

# ---------------------------------------------------------------------------
#  3. HF_TOKEN
# ---------------------------------------------------------------------------
Write-Host "[3/3] Checking HF_TOKEN environment variable ..." -NoNewline
$hf = $env:HF_TOKEN
if ($hf -and $hf.Length -gt 10) {
    Write-Host "  OK  (starts with $($hf.Substring(0,4)))" -ForegroundColor Green
} else {
    Write-Host "  MISSING" -ForegroundColor Red
    $allGood = $false
    Write-Host ""
    Write-Host "  Fix: Set your HuggingFace token" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  1. Get token: https://huggingface.co/settings/tokens (create 'read' token)"
    Write-Host "  2. Accept model terms: https://huggingface.co/google/timesfm-2.5-200m-pytorch"
    Write-Host ""
    Write-Host "  3. Set in current PowerShell session:"
    Write-Host "     `$env:HF_TOKEN = 'hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'"
    Write-Host ""
    Write-Host "  4. (Optional) Persist for future sessions:"
    Write-Host "     [Environment]::SetEnvironmentVariable('HF_TOKEN', 'hf_...', 'User')"
    Write-Host ""
}

# ---------------------------------------------------------------------------
#  Summary
# ---------------------------------------------------------------------------
Write-Host "============================================" -ForegroundColor Cyan
if ($allGood) {
    Write-Host "  ALL CHECKS PASSED" -ForegroundColor Green
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Next step: deploy to Azure" -ForegroundColor Green
    Write-Host ""
    Write-Host "  cd timesfm-service"
    Write-Host "  .\deploy-azure.ps1 -HF_TOKEN `$env:HF_TOKEN"
    Write-Host ""
} else {
    Write-Host "  SOME CHECKS FAILED" -ForegroundColor Red
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Fix the issues above, then run this script again." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "If you prefer not to install Azure CLI, use the manual portal method:"
    Write-Host "  See: timesfm-service/DEPLOYMENT-GUIDE.md  (Option B)"
    Write-Host ""
}
