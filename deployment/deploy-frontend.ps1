# ============================================================
# deploy-frontend.ps1
# Deploys ProspektLab frontend to AWS Amplify (ap-south-1)
# via local build + manual zip upload
#
# Deploys to BOTH branches:
#   main       -> https://main.d1z5h6v6ty54e7.amplifyapp.com
#   production -> https://prospektlab.com  (custom domain)
#
# Usage:  cd D:\PROSPEKTLAB
#         .\deployment\deploy-frontend.ps1
# ============================================================
$ErrorActionPreference = "Stop"

$Region      = "ap-south-1"
$AppId       = "d1z5h6v6ty54e7"
# prospektlab.com -> production branch | app.prospektlab.com -> main branch
$Branches    = @("main", "production")
$RootDir     = Split-Path -Parent $PSScriptRoot
$FrontendDir = Join-Path $RootDir "frontend"
$DistDir     = Join-Path $FrontendDir "dist"
$ZipPath     = Join-Path $RootDir "frontend.zip"

Write-Host "[Frontend Deploy] ProspektLab -> AWS Amplify (ap-south-1)" -ForegroundColor Cyan
Write-Host ""

# --- Step 1: Build Vite frontend ----------------------------
Write-Host "[1/3] Building Vite frontend..." -ForegroundColor Yellow
Push-Location $FrontendDir
try {
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
} finally {
    Pop-Location
}
Write-Host "[1/3] Build complete: $DistDir" -ForegroundColor Green

# --- Step 2: Zip dist/ contents ----------------------------
Write-Host ""
Write-Host "[2/3] Zipping dist/ folder..." -ForegroundColor Yellow
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path "$DistDir\*" -DestinationPath $ZipPath -Force
$ZipSizeMB = [math]::Round((Get-Item $ZipPath).Length / 1MB, 2)
Write-Host "[2/3] Created frontend.zip ($ZipSizeMB MB)" -ForegroundColor Green

# --- Step 3: Deploy to each branch -------------------------
Write-Host ""
Write-Host "[3/3] Deploying to branches: $($Branches -join ', ')..." -ForegroundColor Yellow

foreach ($Branch in $Branches) {
    Write-Host ""
    Write-Host "  --> Branch: $Branch" -ForegroundColor Cyan

    # Create deployment slot
    $DeploymentInfo = $(aws amplify create-deployment --app-id $AppId --branch-name $Branch --region $Region --output json 2>&1) | ConvertFrom-Json
    $JobId     = $DeploymentInfo.jobId
    $UploadUrl = $DeploymentInfo.zipUploadUrl
    Write-Host "      Slot created: Job $JobId" -ForegroundColor DarkCyan

    # Upload zip
    $HttpCode = curl.exe -s -o NUL -w "%{http_code}" -X PUT -H "Content-Type: application/zip" --data-binary "@$ZipPath" "$UploadUrl"
    if ($HttpCode -ne "200") { throw "Upload to $Branch failed: HTTP $HttpCode" }
    Write-Host "      Upload OK (HTTP 200)" -ForegroundColor DarkCyan

    # Start deployment
    aws amplify start-deployment --app-id $AppId --branch-name $Branch --job-id $JobId --region $Region | Out-Null
    Write-Host "      Deployment started..." -ForegroundColor DarkCyan

    # Poll until complete
    $Start = Get-Date
    while ($true) {
        Start-Sleep -Seconds 12
        $Status = $(aws amplify get-job --app-id $AppId --branch-name $Branch --job-id $JobId --region $Region --query "job.summary.status" --output text 2>&1).Trim()
        $Secs = [int]((Get-Date) - $Start).TotalSeconds
        Write-Host "      [$Secs s] $Status" -ForegroundColor DarkGray
        if ($Status -eq "SUCCEED") { Write-Host "      Branch ${Branch}: DEPLOYED" -ForegroundColor Green; break }
        if ($Status -eq "FAILED")  { throw "Deploy to $Branch FAILED. Check: https://$Region.console.aws.amazon.com/amplify/apps/$AppId" }
        if ($Status -eq "CANCELLED") { throw "Deploy to $Branch was CANCELLED." }
    }
}

Write-Host ""
Write-Host "=== ALL BRANCHES DEPLOYED ===" -ForegroundColor Green
Write-Host "  https://prospektlab.com          (production branch)" -ForegroundColor Green
Write-Host "  https://www.prospektlab.com       (production branch)" -ForegroundColor Green
Write-Host "  https://main.d1z5h6v6ty54e7.amplifyapp.com (main branch)" -ForegroundColor Green
