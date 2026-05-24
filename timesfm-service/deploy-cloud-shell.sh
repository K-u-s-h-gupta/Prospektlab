#!/bin/bash
# ---------------------------------------------------------------------------
#  TimesFM 2.5 200M — Azure Deployment Script (Bash / Cloud Shell)
# ---------------------------------------------------------------------------
# Run this INSIDE Azure Cloud Shell (https://shell.azure.com)
# Select BASH (not PowerShell) when Cloud Shell starts.
#
# Usage:
#   1. Upload deploy-package.zip to Cloud Shell
#   2. Expand-Archive deploy-package.zip -DestinationPath timesfm-service -Force
#   3. cd timesfm-service
#   4. bash deploy-cloud-shell.sh
#
# The script will prompt for your HF_TOKEN interactively.
# ---------------------------------------------------------------------------

set -euo pipefail

# ---------------------------------------------------------------------------
#  Config (edit if you want different names)
# ---------------------------------------------------------------------------
RESOURCE_GROUP="rg-timesfm"
LOCATION="eastus"
APP_NAME="timesfm-inference"
# Generate a random suffix for globally-unique ACR name
ACR_NAME="acrtimesfm$(shuf -i 100000-999999 -n 1)"
IMAGE_TAG="timesfm:1.0.0"

# ---------------------------------------------------------------------------
#  Prompt for HF_TOKEN
# ---------------------------------------------------------------------------
echo ""
echo "========================================"
echo "  TimesFM 2.5 200M — Azure Deployment"
echo "========================================"
echo ""
echo "This script builds the TimesFM Docker image IN AZURE"
echo "and deploys it to Azure Container Apps."
echo ""

read -sp "Enter your HuggingFace token (hf_...): " HF_TOKEN
echo ""

if [[ -z "$HF_TOKEN" ]]; then
    echo "ERROR: HF_TOKEN is required. Get it from https://huggingface.co/settings/tokens"
    exit 1
fi

if [[ ! -f "Dockerfile" ]]; then
    echo "ERROR: Dockerfile not found. Make sure you are in the timesfm-service folder."
    echo "Hint: cd timesfm-service"
    exit 1
fi

# ---------------------------------------------------------------------------
#  1. Azure login check
# ---------------------------------------------------------------------------
echo ""
echo "[1/6] Checking Azure login..."
ACCOUNT=$(az account show --query name -o tsv 2>/dev/null || true)
if [[ -z "$ACCOUNT" ]]; then
    echo "  -> Not logged in. Running 'az login'..."
    az login
else
    echo "  -> Logged in as: $ACCOUNT"
fi

# ---------------------------------------------------------------------------
#  2. Resource Group
# ---------------------------------------------------------------------------
echo ""
echo "[2/6] Ensuring resource group '$RESOURCE_GROUP' ..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none
echo "  -> OK"

# ---------------------------------------------------------------------------
#  3. Azure Container Registry
# ---------------------------------------------------------------------------
echo ""
echo "[3/6] Creating Azure Container Registry '$ACR_NAME' ..."
az acr create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$ACR_NAME" \
    --sku Standard \
    --location "$LOCATION" \
    --admin-enabled true \
    --output none
echo "  -> OK"

# ---------------------------------------------------------------------------
#  4. Build Docker image in Azure (ACR Task)
# ---------------------------------------------------------------------------
echo ""
echo "[4/6] Building Docker image in Azure ACR..."
echo "  -> This will take 10-20 minutes (downloads ~300 MB model weights)..."
echo ""

az acr build \
    --registry "$ACR_NAME" \
    --image "$IMAGE_TAG" \
    --build-arg "HF_TOKEN=$HF_TOKEN" \
    --resource-group "$RESOURCE_GROUP" \
    --file Dockerfile \
    . \
    --output none

echo "  -> Image build complete."

# ---------------------------------------------------------------------------
#  5. Container Apps Environment
# ---------------------------------------------------------------------------
ENV_NAME="cae-$APP_NAME"
echo ""
echo "[5/6] Creating Container Apps environment '$ENV_NAME' ..."
az containerapp env create \
    --name "$ENV_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --output none
echo "  -> OK"

# ---------------------------------------------------------------------------
#  6. Deploy Container App
# ---------------------------------------------------------------------------
echo ""
echo "[6/6] Deploying Container App '$APP_NAME' ..."

FULL_IMAGE="$ACR_NAME.azurecr.io/$IMAGE_TAG"
SECRETS_JSON='[{"name":"hf-token","value":"'$HF_TOKEN'"}]'
ENV_VARS_JSON='[{"name":"PORT","value":"8000"},{"name":"MCP_PORT","value":"8001"},{"name":"HF_TOKEN","secretRef":"hf-token"}]'

az containerapp create \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --environment "$ENV_NAME" \
    --image "$FULL_IMAGE" \
    --cpu 2 \
    --memory "4Gi" \
    --min-replicas 0 \
    --max-replicas 3 \
    --target-port 8000 \
    --ingress external \
    --transport auto \
    --secrets "$SECRETS_JSON" \
    --env-vars "$ENV_VARS_JSON" \
    --output none

echo "  -> OK"

# ---------------------------------------------------------------------------
#  7. Output URL
# ---------------------------------------------------------------------------
FQDN=$(az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" --query properties.configuration.ingress.fqdn -o tsv)

ENDPOINT="https://$FQDN"

echo ""
echo "========================================"
echo "  DEPLOYMENT COMPLETE"
echo "========================================"
echo ""
echo "Container App FQDN:  $FQDN"
echo "REST Base URL:       $ENDPOINT"
echo "Forecast endpoint:   $ENDPOINT/forecast"
echo "Anomaly endpoint:    $ENDPOINT/anomaly"
echo "Health endpoint:     $ENDPOINT/health"
echo ""
echo "Test with curl:"
echo "  curl $ENDPOINT/health"
echo ""
echo "Test forecast:"
echo "  curl -X POST $ENDPOINT/forecast -H 'Content-Type: application/json' -d '{\"values\":[120,128,135,142,151,158,167],\"horizon\":4}'"
echo ""
echo "Add to your local .env file:"
echo "  TIMESFM_REMOTE_URL=$ENDPOINT"
echo ""
echo "To delete everything later:"
echo "  az group delete --name $RESOURCE_GROUP --yes"
echo ""
