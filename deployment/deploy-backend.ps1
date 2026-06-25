    # ============================================================
# deploy-backend.ps1
# Deploys ProspektLab backend to ECS (ap-south-1) via CodeBuild
#
# Usage:  cd D:\PROSPEKTLAB
#         .\deployment\deploy-backend.ps1
# ============================================================

$ErrorActionPreference = "Stop"

# ── Config ──────────────────────────────────────────────────
$Region          = "ap-south-1"
$AccountId       = "121488480221"
$S3Bucket        = "finagent-backend-src-ap-south-1-$AccountId"
$S3Key           = "backend.zip"
$CodeBuildProject= "finagent-backend-build"
$EcsCluster      = "finagent-backend"
$EcsService      = "finagent-backend"
$RootDir         = Split-Path -Parent $PSScriptRoot   # D:\PROSPEKTLAB

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  ProspektLab Backend Deploy — ECS (ap-south-1)  ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Create zip from local backend/ ──────────────────
Write-Host "📦 [1/4] Zipping local backend..." -ForegroundColor Yellow

$ZipPath = Join-Path $RootDir ("backend-{0}.zip" -f (Get-Date -Format "yyyyMMdd-HHmmss"))

# Zip using Python to ensure forward-slashes in the zip file! (CodeBuild Linux needs this)
Write-Host "   Running zip_backend.py to create POSIX-compliant zip..."
python .\deployment\zip_backend.py

if (-not (Test-Path "backend.zip")) {
    throw "❌ Python zip script failed to create backend.zip"
}

Move-Item -Path "backend.zip" -Destination $ZipPath -Force

$ZipSizeMB = [math]::Round((Get-Item $ZipPath).Length / 1MB, 2)
Write-Host "   ✅ Created $(Split-Path -Leaf $ZipPath) ($ZipSizeMB MB)" -ForegroundColor Green

# ── Step 2: Upload to S3 ────────────────────────────────────
Write-Host ""
Write-Host "☁️  [2/4] Uploading to S3: s3://$S3Bucket/$S3Key ..." -ForegroundColor Yellow

aws s3 cp $ZipPath "s3://$S3Bucket/$S3Key" --region $Region
if ($LASTEXITCODE -ne 0) { throw "❌ S3 upload failed" }

Write-Host "   ✅ Uploaded successfully" -ForegroundColor Green

# ── Step 3: Trigger CodeBuild ───────────────────────────────
Write-Host ""
Write-Host "🔨 [3/4] Triggering CodeBuild project: $CodeBuildProject ..." -ForegroundColor Yellow

$BuildResponseRaw = aws codebuild start-build --project-name $CodeBuildProject --region $Region --output json 2>&1
if ($LASTEXITCODE -ne 0) { throw "? CodeBuild trigger failed. Output: $BuildResponseRaw" }

try {
    $BuildId = (($BuildResponseRaw | ConvertFrom-Json).build.id).Trim()
}
catch {
    throw "? CodeBuild trigger returned unreadable JSON. Output: $BuildResponseRaw"
}

if (-not $BuildId) { throw "? CodeBuild trigger did not return build id. Output: $BuildResponseRaw" }
Write-Host "   ✅ Build started: $BuildId" -ForegroundColor Green
Write-Host ""
Write-Host "   🔗 Monitor at:" -ForegroundColor DarkGray
$EncodedBuildId = [uri]::EscapeDataString($BuildId)
Write-Host "   https://$Region.console.aws.amazon.com/codesuite/codebuild/$AccountId/projects/$CodeBuildProject/build/$EncodedBuildId" -ForegroundColor DarkGray

# ── Step 4: Poll CodeBuild status ───────────────────────────
Write-Host ""
Write-Host "⏳ [4/4] Waiting for CodeBuild to finish (polls every 30s)..." -ForegroundColor Yellow

$StartTime = Get-Date
while ($true) {
    Start-Sleep -Seconds 30
    $Status = (aws codebuild batch-get-builds `
        --ids $BuildId `
        --region $Region `
        --query "builds[0].buildStatus" `
        --output text)

    $Elapsed = [int]((Get-Date) - $StartTime).TotalMinutes
    Write-Host "   [$Elapsed min] Status: $Status" -ForegroundColor DarkCyan

    switch ($Status) {
        "SUCCEEDED" {
            Write-Host ""
            Write-Host "╔═══════════════════════════════════════╗" -ForegroundColor Green
            Write-Host "║  ✅ Backend deploy COMPLETE!           ║" -ForegroundColor Green
            Write-Host "╚═══════════════════════════════════════╝" -ForegroundColor Green
            Write-Host ""
            Write-Host "ECS Service is rolling out new tasks..." -ForegroundColor Cyan
            Write-Host "Check: https://$Region.console.aws.amazon.com/ecs/v2/clusters/$EcsCluster/services/$EcsService" -ForegroundColor Cyan

            # Get running task public IP
            Write-Host ""
            Write-Host "📡 Fetching ECS task public IP..." -ForegroundColor Yellow
            $TaskArn = (aws ecs list-tasks --cluster $EcsCluster --service-name $EcsService --region $Region --query "taskArns[0]" --output text 2>$null)
            if ($TaskArn -and $TaskArn -ne "None") {
                $EniId = (aws ecs describe-tasks --cluster $EcsCluster --tasks $TaskArn --region $Region --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value" --output text 2>$null)
                if ($EniId) {
                    $PublicIp = (aws ec2 describe-network-interfaces --network-interface-ids $EniId --region $Region --query "NetworkInterfaces[0].Association.PublicIp" --output text 2>$null)
                    if ($PublicIp -and $PublicIp -ne "None") {
                        Write-Host "   🌐 Backend public IP: http://$PublicIp`:8080" -ForegroundColor Green
                        Write-Host "   Health check: http://$PublicIp`:8080/health" -ForegroundColor Green
                    }
                }
            }
            exit 0
        }
        "FAILED" {
            Write-Host "❌ CodeBuild FAILED. Check logs:" -ForegroundColor Red
            Write-Host "   https://$Region.console.aws.amazon.com/codesuite/codebuild/$AccountId/projects/$CodeBuildProject/build/$($BuildId.Replace(':','%3A'))" -ForegroundColor Red
            exit 1
        }
        "FAULT" {
            Write-Host "❌ CodeBuild FAULT (infrastructure issue). Retry." -ForegroundColor Red
            exit 1
        }
        "STOPPED" {
            Write-Host "⚠️  CodeBuild was STOPPED manually." -ForegroundColor Yellow
            exit 1
        }
        default {
            # IN_PROGRESS or QUEUED — keep polling
        }
    }
}






