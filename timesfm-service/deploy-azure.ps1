<#
.SYNOPSIS
    Build TimesFM service image, push to Azure Container Registry,
    and deploy to Azure Container Apps.

.DESCRIPTION
    One-click deployment script for the standalone TimesFM 2.5 200M
    inference service.  You must be logged into Azure (az login) and
    have Docker running.

.PARAMETER HF_TOKEN
    Your HuggingFace token (required to download the gated model during build).

.PARAMETER ResourceGroup
    Azure resource group name.  Default: rg-timesfm

.PARAMETER Location
    Azure region.  Default: eastus

.PARAMETER AcrName
    Azure Container Registry name (globally unique, 5-50 chars, alphanumeric).
    Default: acrtimesfm{random}

.PARAMETER AppName
    Azure Container App name.  Default: timesfm-inference

.PARAMETER ImageTag
    Docker image tag.  Default: timesfm:1.0.0

.EXAMPLE
    .\deploy-azure.ps1 -HF_TOKEN "hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

.EXAMPLE
    .\deploy-azure.ps1 -HF_TOKEN $env:HF_TOKEN -Location "westeurope" -AppName "timesfm-prod"
#>

param(
    [Parameter(Mandatory = $true)]
    [string] $HF_TOKEN,

    [string] $ResourceGroup = "rg-timesfm",
    [string] $Location = "eastus",
    [string] $AcrName = "",
    [string] $AppName = "timesfm-inference",
    [string] $ImageTag = "timesfm:1.0.0",

    [int] $Cpu = 2,
    [int] $MemoryGiB = 4,
    [int] $MinReplicas = 0,
    [int] $MaxReplicas = 3
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
#  Validation
# ---------------------------------------------------------------------------
function Test-Command($cmd) {
    $null = Get-Command $cmd -ErrorAction SilentlyContinue
    return $?
}

if (-not (Test-Command "az")) {
    Write-Error "Azure CLI (az) not found. Install: https://aka.ms/installazurecli"
    exit 1
}
if (-not (Test-Command "docker")) {
    Write-Error "Docker not found. Install Docker Desktop / Engine and ensure the daemon is running."
    exit 1
}

Write-Host "=== TimesFM 2.5 200M — Azure Container Apps Deployment ===" -ForegroundColor Cyan
Write-Host "Region:        $Location"
Write-Host "ResourceGroup: $ResourceGroup"
Write-Host "AppName:       $AppName"
Write-Host ""

# ---------------------------------------------------------------------------
#  Derive ACR name if not provided (must be globally unique)
# ---------------------------------------------------------------------------
if ([string]::IsNullOrWhiteSpace($AcrName)) {
    $suffix = -join ((1..6) | ForEach-Object { Get-Random -Maximum 10 })
    $AcrName = "acrtimesfm$suffix"
    Write-Host "Generated ACR name: $AcrName" -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
#  Ensure logged into Azure
# ---------------------------------------------------------------------------
$account = az account show --output json 2>$null | ConvertFrom-Json
if (-not $account) {
    Write-Host "Logging into Azure..." -ForegroundColor Yellow
    az login
}
$subName = (az account show --query name -o tsv)
Write-Host "Subscription: $subName" -ForegroundColor Green

# ---------------------------------------------------------------------------
#  1. Resource Group
# ---------------------------------------------------------------------------
Write-Host "`n[1/6] Ensuring resource group '$ResourceGroup' ..." -ForegroundColor Cyan
$rg = az group show --name $ResourceGroup --output json 2>$null | ConvertFrom-Json
if (-not $rg) {
    Write-Host "  -> Creating resource group ..."
    az group create --name $ResourceGroup --location $Location --output none
    Write-Host "  -> Created." -ForegroundColor Green
} else {
    Write-Host "  -> Already exists." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
#  2. Azure Container Registry
# ---------------------------------------------------------------------------
Write-Host "`n[2/6] Ensuring ACR '$AcrName' ..." -ForegroundColor Cyan
$acr = az acr show --name $AcrName --resource-group $ResourceGroup --output json 2>$null | ConvertFrom-Json
if (-not $acr) {
    Write-Host "  -> Creating ACR (Standard tier) ..."
    az acr create `
        --resource-group $ResourceGroup `
        --name $AcrName `
        --sku Standard `
        --location $Location `
        --admin-enabled true `
        --output none
    Write-Host "  -> Created." -ForegroundColor Green
} else {
    Write-Host "  -> Already exists." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
#  3. Build & push Docker image
# ---------------------------------------------------------------------------
Write-Host "`n[3/6] Building Docker image (this may take 10–20 min on first run because it downloads ~300 MB model weights) ..." -ForegroundColor Cyan

$acrLoginServer = (az acr show --name $AcrName --resource-group $ResourceGroup --query loginServer -o tsv)
$fullImageName = "$acrLoginServer/$ImageTag"

# Login to ACR
Write-Host "  -> Logging into ACR ..."
az acr login --name $AcrName --output none

# Build and push (using ACR Tasks so we don't need local docker push bandwidth)
Write-Host "  -> Submitting ACR build task ..."
az acr build `
    --registry $AcrName `
    --image $ImageTag `
    --build-arg "HF_TOKEN=$HF_TOKEN" `
    --resource-group $ResourceGroup `
    --file Dockerfile `
    . `
    --output none

Write-Host "  -> Image pushed to $fullImageName" -ForegroundColor Green

# ---------------------------------------------------------------------------
#  4. Azure Container Apps Environment
# ---------------------------------------------------------------------------
Write-Host "`n[4/6] Ensuring Container Apps environment ..." -ForegroundColor Cyan
$envName = "cae-$AppName"
$cae = az containerapp env show --name $envName --resource-group $ResourceGroup --output json 2>$null | ConvertFrom-Json
if (-not $cae) {
    Write-Host "  -> Creating environment '$envName' ..."
    az containerapp env create `
        --name $envName `
        --resource-group $ResourceGroup `
        --location $Location `
        --output none
    Write-Host "  -> Created." -ForegroundColor Green
} else {
    Write-Host "  -> Already exists." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
#  5. Deploy Container App
# ---------------------------------------------------------------------------
Write-Host "`n[5/6] Deploying Container App '$AppName' ..." -ForegroundColor Cyan

# Build JSON for secrets (HF_TOKEN as a secret, injected as env var)
$secretsJson = @(
    @{ name = "hf-token"; value = $HF_TOKEN }
) | ConvertTo-Json -Compress

$envVarsJson = @(
    @{ name = "HF_TOKEN"; secretRef = "hf-token" },
    @{ name = "PORT"; value = "8000" },
    @{ name = "MCP_PORT"; value = "8001" }
) | ConvertTo-Json -Compress

$app = az containerapp show --name $AppName --resource-group $ResourceGroup --output json 2>$null | ConvertFrom-Json
if (-not $app) {
    Write-Host "  -> Creating new container app ..."
    az containerapp create `
        --name $AppName `
        --resource-group $ResourceGroup `
        --environment $envName `
        --image $fullImageName `
        --cpu $Cpu `
        --memory "${MemoryGiB}Gi" `
        --min-replicas $MinReplicas `
        --max-replicas $MaxReplicas `
        --target-port 8000 `
        --ingress external `
        --transport auto `
        --secrets "$secretsJson" `
        --env-vars "$envVarsJson" `
        --query configuration.ingress.fqdn `
        --output tsv
} else {
    Write-Host "  -> Updating existing container app ..."
    az containerapp update `
        --name $AppName `
        --resource-group $ResourceGroup `
        --image $fullImageName `
        --cpu $Cpu `
        --memory "${MemoryGiB}Gi" `
        --min-replicas $MinReplicas `
        --max-replicas $MaxReplicas `
        --secrets "$secretsJson" `
        --env-vars "$envVarsJson" `
        --output none
}

# ---------------------------------------------------------------------------
#  6. Verify & output endpoint
# ---------------------------------------------------------------------------
Write-Host "`n[6/6] Waiting for app to report healthy ..." -ForegroundColor Cyan
$fqdn = az containerapp show --name $AppName --resource-group $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv
$endpoint = "https://$fqdn"

Write-Host ""
Write-Host "=== DEPLOYMENT COMPLETE ===" -ForegroundColor Green
Write-Host "Container App FQDN:  $fqdn"
Write-Host "REST Base URL:       $endpoint"
Write-Host "Forecast endpoint:   ${endpoint}/forecast"
Write-Host "Anomaly endpoint:    ${endpoint}/anomaly"
Write-Host "Health endpoint:     ${endpoint}/health"
Write-Host ""
Write-Host "Test with curl:"
Write-Host "  curl -X POST ${endpoint}/health"
Write-Host ""
Write-Host "To update your local .env, add:"
Write-Host "  TIMESFM_REMOTE_URL=${endpoint}"
Write-Host ""
