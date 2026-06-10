# Deploys the Azure monitoring stack only:
# Log Analytics workspace + workspace-based Application Insights + Microsoft Sentinel onboarding.

param(
    [string]$ResourceGroup = "prospektlab-monitoring-rg",
    [string]$Location = "centralindia",
    [string]$WorkspaceName = "prospektlab-monitoring",
    [string]$AppInsightsName = "prospektlab-tracker",
    [int]$RetentionInDays = 90,
    [int]$DailyQuotaGb = 50
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($env:AZURE_CONFIG_DIR)) {
    $env:AZURE_CONFIG_DIR = "D:\\PROSPEKTLAB\\.tmp\\azurecli"
}

try {
    az account show --output none | Out-Null
} catch {
    throw "Azure CLI is not signed in yet. Complete the device-code login first, then rerun this script."
}

Write-Host "Creating resource group if needed..." -ForegroundColor Cyan
az group create --name $ResourceGroup --location $Location | Out-Null

Write-Host "Deploying Azure monitoring resources..." -ForegroundColor Cyan
az deployment group create `
  --resource-group $ResourceGroup `
  --template-file deployment/azure-monitoring.bicep `
  --parameters location=$Location workspaceName=$WorkspaceName appInsightsName=$AppInsightsName retentionInDays=$RetentionInDays dailyQuotaGb=$DailyQuotaGb

Write-Host "Done. Open the resource group in the Azure portal to copy the Application Insights connection string." -ForegroundColor Green
