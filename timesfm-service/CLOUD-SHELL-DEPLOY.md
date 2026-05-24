# Deploy TimesFM Using Azure Cloud Shell (NO Local Software Needed)

**This guide requires ZERO installation on your laptop.**  
You only need:
- A web browser
- Your Azure subscription (already have it)
- Your HuggingFace token

Everything runs in Azure's free browser-based terminal.

---

## Overview

1. Open **Azure Cloud Shell** in your browser (has Docker + Azure CLI built-in)
2. Upload the deployment package
3. Run **4 commands** to build and deploy
4. Copy the URL and use it

That's it. No Docker Desktop. No Azure CLI installation. No PowerShell scripts.

---

## Step 1: Open Azure Cloud Shell

1. Go to **https://shell.azure.com**
2. Sign in with your Microsoft account (same one with Azure subscription)
3. When it asks **Bash or PowerShell?** — pick **PowerShell**
4. Wait 10–30 seconds for the black terminal to appear

**What you see:** A terminal running inside your browser. It already has `az`, `docker`, `git`, and everything else pre-installed.

---

## Step 2: Upload the Deployment Package

I created a zip file for you: **`timesfm-service/deploy-package.zip`**

### In Cloud Shell, click the Upload button:

1. Look at the toolbar above the terminal
2. Click the **paper/document icon** (Upload button)
3. Select this file from your laptop:
   ```
   C:\Users\kusha\OneDrive\डेस्कटॉप\PROSPEKTLAB\timesfm-service\deploy-package.zip
   ```
4. Wait for it to upload

### Extract the files

In the Cloud Shell terminal, type:

```powershell
Expand-Archive -Path deploy-package.zip -DestinationPath timesfm-service -Force
cd timesfm-service
ls
```

You should see:
```
Dockerfile
main.py
mcp_server.py
requirements.txt
```

---

## Step 3: Set Your Variables

Type these in the Cloud Shell terminal. Replace `hf_your_token` with your actual HuggingFace token.

```powershell
$env:HF_TOKEN = "hf_your_actual_token_here"
$ResourceGroup = "rg-timesfm"
$Location = "eastus"
$AcrName = "acrtimesfm$(Get-Random -Maximum 999999)"
$AppName = "timesfm-inference"
```

**Important:**
- If you don't have your HuggingFace token:
  1. Go to https://huggingface.co/settings/tokens
  2. Create a **Read** token
  3. Go to https://huggingface.co/google/timesfm-2.5-200m-pytorch and click **Access repository**
  4. Copy the token and paste it above

---

## Step 4: Run the 4 Deployment Commands

These build the image IN AZURE (not on your laptop) and deploy it.

### Command 1: Login to Azure

```powershell
az login
```

This opens a browser tab. Sign in, then come back to Cloud Shell. You should see a list of your subscriptions.

### Command 2: Create Resource Group and Container Registry

```powershell
# Create resource group
az group create --name $ResourceGroup --location $Location

# Create Azure Container Registry (stores your Docker image)
az acr create --resource-group $ResourceGroup --name $AcrName --sku Standard --location $Location --admin-enabled true

Write-Host "ACR Name: $AcrName"
```

Wait ~1 minute. It will print the ACR name. **Copy it** — you'll need it in the next command.

### Command 3: Build the Docker Image in Azure

This is the magic command. It builds the image using Azure's servers (not your laptop), so it doesn't matter that Docker failed to install on your computer.

```powershell
# Build the image in Azure Container Registry
# This takes 10-20 minutes because it downloads the ~300MB TimesFM model weights
az acr build `
    --registry $AcrName `
    --image timesfm:1.0.0 `
    --build-arg "HF_TOKEN=$env:HF_TOKEN" `
    --resource-group $ResourceGroup `
    --file Dockerfile `
    .
```

**What happens:**
- Azure downloads Python packages
- Downloads TimesFM 2.5 200M model from HuggingFace
- Bakes everything into a Docker image
- Stores it in your registry

You'll see lots of output. When it says `Run ID: xxx was successful`, you're done.

### Command 4: Deploy to Container Apps

```powershell
# Create Container Apps environment
az containerapp env create --name "cae-timesfm" --resource-group $ResourceGroup --location $Location

# Deploy the app
az containerapp create `
    --name $AppName `
    --resource-group $ResourceGroup `
    --environment "cae-timesfm" `
    --image "$AcrName.azurecr.io/timesfm:1.0.0" `
    --cpu 2 `
    --memory "4Gi" `
    --min-replicas 0 `
    --max-replicas 3 `
    --target-port 8000 `
    --ingress external `
    --transport auto `
    --secrets "[{\"name\":\"hf-token\",\"value\":\"$env:HF_TOKEN\"}]" `
    --env-vars "PORT=8000" "MCP_PORT=8001" "HF_TOKEN=secretref:hf-token"

# Get the public URL
$fqdn = az containerapp show --name $AppName --resource-group $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv
Write-Host ""
Write-Host "=== DEPLOYMENT COMPLETE ===" -ForegroundColor Green
Write-Host "Your TimesFM API URL: https://$fqdn" -ForegroundColor Green
Write-Host ""
Write-Host "Test it:"
Write-Host "  curl https://$fqdn/health"
Write-Host ""
Write-Host "Add this to your finagent/.env:"
Write-Host "  TIMESFM_REMOTE_URL=https://$fqdn" -ForegroundColor Yellow
```

Wait 2–3 minutes for the app to start. It will print your HTTPS URL.

---

## Step 5: Test Your Deployment

In Cloud Shell, run:

```powershell
# Replace with YOUR URL from the output above
curl https://timesfm-inference.xxxxx.eastus.azurecontainerapps.io/health
```

If you see `{"status":"ok"...}`, it's working!

Test a forecast:

```powershell
curl -X POST https://timesfm-inference.xxxxx.eastus.azurecontainerapps.io/forecast `
  -H "Content-Type: application/json" `
  -d '{"values":[120,128,135,142,151,158,167],"horizon":4}'
```

---

## Step 6: Connect Your Local Project

Open this file on your laptop:
```
C:\Users\kusha\OneDrive\डेस्कटॉप\PROSPEKTLAB\finagent\.env
```

Add this line (use the URL from Step 4):
```bash
TIMESFM_REMOTE_URL=https://timesfm-inference.xxxxx.eastus.azurecontainerapps.io
```

Save the file. Done. Your local finagent now calls Azure automatically.

---

## Quick Troubleshooting

### "az acr build" fails with 401 or "Repository Not Found"

Your HuggingFace token is wrong or you haven't accepted the model terms:
1. Go to https://huggingface.co/google/timesfm-2.5-200m-pytorch
2. Click **Access repository** (must be logged in)
3. Create a new token at https://huggingface.co/settings/tokens
4. Re-run Command 3 with the new token

### The app URL returns "Service Unavailable"

The container is still starting and loading the model. Wait 2–3 minutes, then retry.

### "Out of memory" or container keeps restarting

Make sure you used `--memory "4Gi"` (not the default 1Gi).

### How do I delete everything and stop billing?

In Cloud Shell:
```powershell
az group delete --name rg-timesfm --yes
```
This deletes the entire resource group (registry + app + everything) in one shot.

---

## Cost Summary

| Service | Monthly Cost |
|---------|-------------|
| Container Registry (Standard) | ~$5 |
| Container App (2 CPU, 4 GiB, scales to 0) | $0 when idle, ~$5–20 with moderate use |
| **Total** | **~$5–25/month** |

To pay $0: Delete the resource group when you're done testing.

---

## The 4 Commands Summary

```powershell
# 1. Login
az login

# 2. Setup (create group + registry)
$env:HF_TOKEN = "hf_your_token"
$ResourceGroup = "rg-timesfm"
$Location = "eastus"
$AcrName = "acrtimesfm$(Get-Random -Maximum 999999)"
az group create --name $ResourceGroup --location $Location
az acr create --resource-group $ResourceGroup --name $AcrName --sku Standard --location $Location --admin-enabled true

# 3. Build image in Azure
az acr build --registry $AcrName --image timesfm:1.0.0 --build-arg "HF_TOKEN=$env:HF_TOKEN" --resource-group $ResourceGroup --file Dockerfile .

# 4. Deploy app
az containerapp env create --name "cae-timesfm" --resource-group $ResourceGroup --location $Location
az containerapp create --name "timesfm-inference" --resource-group $ResourceGroup --environment "cae-timesfm" --image "$AcrName.azurecr.io/timesfm:1.0.0" --cpu 2 --memory "4Gi" --min-replicas 0 --max-replicas 3 --target-port 8000 --ingress external --transport auto --secrets "[{\"name\":\"hf-token\",\"value\":\"$env:HF_TOKEN\"}]" --env-vars "PORT=8000" "MCP_PORT=8001" "HF_TOKEN=secretref:hf-token"
```

That's it. No Docker Desktop. No local installation. Just a browser and 4 copy-paste commands.
