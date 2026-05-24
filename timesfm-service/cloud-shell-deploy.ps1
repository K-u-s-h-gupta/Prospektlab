#Requires -Version 5.1
<#
.SYNOPSIS
    Deploy TimesFM to Azure using Cloud Shell commands.

.DESCRIPTION
    This script generates the exact commands you need to copy-paste into
    Azure Cloud Shell (https://shell.azure.com) to build and deploy TimesFM.
    
    You do NOT need Docker Desktop or Azure CLI installed on your laptop.
    Everything runs in Azure's free browser-based terminal.

.PARAMETER HF_TOKEN
    Your HuggingFace token (required for the gated model).

.PARAMETER ResourceGroup
    Default: rg-timesfm

.PARAMETER Location
    Default: eastus

.PARAMETER AppName
    Default: timesfm-inference

.EXAMPLE
    .\cloud-shell-deploy.ps1 -HF_TOKEN "hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
#>

param(
    [Parameter(Mandatory = $true, HelpMessage = "Your HuggingFace token (hf_...)")]
    [string] $HF_TOKEN,

    [string] $ResourceGroup = "rg-timesfm",
    [string] $Location = "eastus",
    [string] $AppName = "timesfm-inference"
)

$AcrName = "acrtimesfm" + (Get-Random -Maximum 999999)

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  TimesFM Cloud Shell Deployment Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "This script does NOT deploy anything itself." -ForegroundColor Yellow
Write-Host "It generates the commands you need to run in Azure Cloud Shell." -ForegroundColor Yellow
Write-Host ""
Write-Host "--- STEP 1 ---" -ForegroundColor Green
Write-Host "Open https://shell.azure.com in your browser"
Write-Host "Sign in, select PowerShell, wait for the terminal."
Write-Host ""
Write-Host "--- STEP 2 ---" -ForegroundColor Green
Write-Host "Upload the file 'deploy-package.zip' using the Upload button"
Write-Host "in Cloud Shell toolbar, then run:"
Write-Host ""
Write-Host "    Expand-Archive -Path deploy-package.zip -DestinationPath timesfm-service -Force"
Write-Host "    cd timesfm-service"
Write-Host ""
Write-Host "--- STEP 3 ---" -ForegroundColor Green
Write-Host "Copy and paste ALL the commands below into Cloud Shell:"
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  START COPY-PASTE BLOCK" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$scriptBlock = @"
# === TimesFM Azure Deployment Commands ===
`$HF_TOKEN = "$HF_TOKEN"
`$ResourceGroup = "$ResourceGroup"
`$Location = "$Location"
`$AcrName = "$AcrName"
`$AppName = "$AppName"

# Login to Azure (opens browser, click back to terminal when done)
az login

# Create resource group
az group create --name `$ResourceGroup --location `$Location

# Create Azure Container Registry
az acr create --resource-group `$ResourceGroup --name `$AcrName --sku Standard --location `$Location --admin-enabled true

Write-Host "ACR Created: `$AcrName"

# Build Docker image IN AZURE (no local Docker needed)
# This takes 10-20 minutes - downloads ~300MB model weights
az acr build `
    --registry `$AcrName `
    --image timesfm:1.0.0 `
    --build-arg "HF_TOKEN=`$HF_TOKEN" `
    --resource-group `$ResourceGroup `
    --file Dockerfile `
    .

# Create Container Apps environment
az containerapp env create --name "cae-`$AppName" --resource-group `$ResourceGroup --location `$Location

# Deploy the app
az containerapp create `
    --name `$AppName `
    --resource-group `$ResourceGroup `
    --environment "cae-`$AppName" `
    --image "`$AcrName.azurecr.io/timesfm:1.0.0" `
    --cpu 2 `
    --memory "4Gi" `
    --min-replicas 0 `
    --max-replicas 3 `
    --target-port 8000 `
    --ingress external `
    --transport auto `
    --secrets '[{"name":"hf-token","value":"`$HF_TOKEN"}]' `
    --env-vars "PORT=8000" "MCP_PORT=8001" "HF_TOKEN=secretref:hf-token"

# Get and display the public URL
`$fqdn = az containerapp show --name `$AppName --resource-group `$ResourceGroup --query properties.configuration.ingress.fqdn -o tsv
Write-Host ""
Write-Host "=== DEPLOYMENT COMPLETE ===" -ForegroundColor Green
Write-Host "Your TimesFM API URL: https://`$fqdn" -ForegroundColor Green
Write-Host ""
Write-Host "Test health: curl https://`$fqdn/health" -ForegroundColor Yellow
Write-Host "Test forecast: curl -X POST https://`$fqdn/forecast -H 'Content-Type: application/json' -d '{`"values`":[120,128,135,142,151,158,167],`"horizon`":4}'" -ForegroundColor Yellow
Write-Host ""
Write-Host "Add to your local .env file:" -ForegroundColor Cyan
Write-Host "  TIMESFM_REMOTE_URL=https://`$fqdn" -ForegroundColor Cyan
"@

Write-Host $scriptBlock -ForegroundColor White

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  END COPY-PASTE BLOCK" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "--- STEP 4 ---" -ForegroundColor Green
Write-Host "Wait 2-3 minutes after the last command finishes."
Write-Host "Then test your URL with the curl commands shown above."
Write-Host ""
Write-Host "--- STEP 5 ---" -ForegroundColor Green
Write-Host "Add the printed TIMESFM_REMOTE_URL to your local file:"
Write-Host "  C:\Users\kusha\OneDrive\डेस्कटॉप\PROSPEKTLAB\finagent\.env"
Write-Host ""
Write-Host "--- To delete everything later ---" -ForegroundColor Red
Write-Host "Run in Cloud Shell:"
Write-Host "  az group delete --name $ResourceGroup --yes"
Write-Host ""
