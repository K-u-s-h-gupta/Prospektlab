# TimesFM Azure Deployment Guide (No CLI Experience Required)

You have **three options** to get TimesFM running in Azure. Pick whichever fits your comfort level.

---

## Option A: Install Azure CLI + One-Click Script (Recommended)

### Step 1: Install Azure CLI

**Method 1 — Winget (fastest, you already have winget):**

```powershell
winget install Microsoft.AzureCLI
```

Restart PowerShell after installation finishes. Then verify:

```powershell
az --version
```

**Method 2 — Direct MSI download (if winget fails):**

```powershell
Invoke-WebRequest -Uri "https://aka.ms/installazurecliwindowsx64" -OutFile "$env:TEMP\AzureCLI.msi"
Start-Process msiexec.exe -Wait -ArgumentList "/I", "$env:TEMP\AzureCLI.msi", "/quiet"
```

Restart PowerShell, then run `az --version`.

### Step 2: Log in to Azure

```powershell
az login
```

This opens your browser. Sign in with the Microsoft account that owns your Azure subscription.

### Step 3: Run the deployment script

```powershell
cd "C:\Users\kusha\OneDrive\डेस्कटॉप\PROSPEKTLAB\timesfm-service"
.\deploy-azure.ps1 -HF_TOKEN $env:HF_TOKEN
```

Wait 10–20 minutes (it bakes ~300 MB model weights into the image). The script prints your HTTPS endpoint when done.

### Step 4: Wire your local project

Copy the printed URL into `finagent/.env`:

```bash
TIMESFM_REMOTE_URL=https://timesfm-inference.xxx.eastus.azurecontainerapps.io
```

Restart your local finagent app. It now calls Azure automatically instead of loading the model locally.

---

## Option B: Manual Deployment via Azure Portal (No Scripts)

If you can't or don't want to install the Azure CLI, use the Azure web portal.

### Step 1: Build the image locally with Docker Desktop

Make sure Docker Desktop is running, then in PowerShell:

```powershell
cd "C:\Users\kusha\OneDrive\डेस्कटॉप\PROSPEKTLAB\timesfm-service"

# Build image with model baked in (takes 10–20 min)
docker build --build-arg HF_TOKEN=$env:HF_TOKEN -t timesfm:1.0.0 .
```

### Step 2: Create Azure Container Registry (Portal)

1. Go to https://portal.azure.com
2. Search "Container registries" → **Create**
3. Fill in:
   - **Subscription**: pick yours
   - **Resource group**: click **Create new** → name it `rg-timesfm`
   - **Registry name**: `acrtimesfm` + random numbers (must be globally unique, e.g. `acrtimesfm123456`)
   - **SKU**: **Standard**
   - **Location**: `East US`
4. Click **Review + create**, then **Create**

Wait for deployment to finish (~1 min).

### Step 3: Push your local image to ACR

Back in PowerShell:

```powershell
# Get your ACR login server name (replace with YOUR actual registry name)
$acrName = "acrtimesfm123456"   # <-- change this!

# Login to ACR
az acr login --name $acrName

# If az is still missing, use Docker directly with the admin password from portal:
#  1. In portal → Container registry → Access keys → Enable "Admin user"
#  2. Copy "Login server", "Username", "password"
#  3. docker login <login-server> -u <username> -p <password>

# Tag image for ACR
docker tag timesfm:1.0.0 "$acrName.azurecr.io/timesfm:1.0.0"

# Push (upload)
docker push "$acrName.azurecr.io/timesfm:1.0.0"
```

### Step 4: Create Container Apps Environment (Portal)

1. In portal, search "Container Apps" → **Create**
2. Basics tab:
   - **Subscription / Resource group**: same as above (`rg-timesfm`)
   - **Container app name**: `timesfm-inference`
   - **Region**: `East US`
3. Environment tab:
   - Click **Create new** environment
   - Name: `cae-timesfm-inference`
4. Click **Next: App settings**

### Step 5: App Settings (Portal)

1. **Use quickstart image**: Uncheck / choose **Custom container**
2. **Image source**: Azure Container Registry
3. Pick your registry, image `timesfm`, tag `1.0.0`
4. **CPU and memory**: `2 cores`, `4 Gi`
5. **Environment variables**:
   - `PORT` = `8000`
   - `MCP_PORT` = `8001`
6. **Secrets** (important — keeps HF token secure):
   - Name: `hf-token` → Value: your `hf_...` token
   - Reference it in env var: `HF_TOKEN` → **Secret reference** → `hf-token`
7. **Ingress**: Enable
   - **Target port**: `8000`
   - **Traffic**: Accepting traffic from anywhere

### Step 6: Create + Test

Click **Review + create**, then **Create**.

Wait 2–3 minutes. Go to the resource → **Application URL** (e.g. `https://timesfm-inference.xxx.eastus.azurecontainerapps.io`).

Test:

```powershell
curl "https://<your-url>/health"
```

Then add the URL to your local `.env`:

```bash
TIMESFM_REMOTE_URL=https://<your-url>
```

---

## Option C: Docker-Only Local Mode (No Azure Needed)

If you just want to run it locally without cloud costs:

```powershell
cd "C:\Users\kusha\OneDrive\डेस्कटॉप\PROSPEKTLAB\timesfm-service"

# Build
docker build --build-arg HF_TOKEN=$env:HF_TOKEN -t timesfm:local .

# Run REST server on localhost:8000
docker run -d -p 8000:8000 --name timesfm-local -e HF_TOKEN=$env:HF_TOKEN timesfm:local

# Test
curl http://localhost:8000/health
curl -X POST http://localhost:8000/forecast `
  -H "Content-Type: application/json" `
  -d '{"values":[120,128,135,142,151,158,167],"horizon":4}'
```

To connect your local finagent to it:

```bash
# In finagent/.env
TIMESFM_REMOTE_URL=http://localhost:8000
```

Stop/remove later:

```powershell
docker stop timesfm-local
docker rm timesfm-local
```

---

## Troubleshooting

### "az is not recognized"

→ Install Azure CLI using one of the Step 1 methods above. **Restart PowerShell** after install.

### Docker build fails with "Repository Not Found" or 401

→ Your HuggingFace token is invalid or you haven't accepted the model terms. Visit https://huggingface.co/google/timesfm-2.5-200m-pytorch, click **Access repository** and accept. Then verify your token with:

```powershell
huggingface-cli login --token $env:HF_TOKEN
```

### Portal deployment shows "Failed" or container keeps restarting

1. In portal → Container App → **Monitoring** → **Log stream**
2. Look for errors (most common: `HF_TOKEN` missing, out of memory, or port mismatch)
3. Make sure **Target port** is `8000` (not 80 or 8080)
4. Make sure **CPU/Memory** is at least `2 cores / 4 GiB`

### How do I update the app after changing code?

Rebuild image, push to same ACR tag, then in portal → Container App → **Revision management** → **Create new revision** → pick the updated image.

Or with CLI:

```powershell
az containerapp update --name timesfm-inference --resource-group rg-timesfm --image acrtimesfm123456.azurecr.io/timesfm:1.0.0
```

### How much does this cost?

- **Container Apps**: ~$0.000024/vCPU/s + ~$0.000003/GiB/s while running. With 2 vCPU / 4 GiB and 0 min replicas (scales to zero when idle), you're looking at roughly **$15–30/month** if it gets regular traffic, or **near $0** if it sits idle.
- **Container Registry**: ~$5/month (Standard SKU).

---

## Quick Reference: Files You Need

| File | Path |
|------|------|
| Service code | `PROSPEKTLAB/timesfm-service/main.py` |
| MCP server | `PROSPEKTLAB/timesfm-service/mcp_server.py` |
| Dockerfile | `PROSPEKTLAB/timesfm-service/Dockerfile` |
| Deploy script | `PROSPEKTLAB/timesfm-service/deploy-azure.ps1` |
| Local env | `PROSPEKTLAB/finagent/.env` |

