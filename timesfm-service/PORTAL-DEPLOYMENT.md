# Deploy TimesFM to Azure Using Only the Azure Portal + 4 Docker Commands

**You do NOT need Azure CLI (`az`).**  
**You only need Docker Desktop to build the image, then everything else is point-and-click in the Azure web portal.**

---

## Overview of Steps

1. **Install Docker Desktop** (one-time, 5 minutes)
2. **Build the TimesFM image on your laptop** (1 command, ~10–20 min)
3. **Create an Azure Container Registry in the portal** (2 minutes)
4. **Push the image to Azure using Docker** (2 commands, 2 minutes)
5. **Create the Container App in the portal** (3 minutes)
6. **Connect your local project** (copy-paste a URL)

Total Azure portal clicks: about **15**.  
Total Docker commands: **4**.

---

## Step 1: Install Docker Desktop

### Why you need it
Azure can't build a custom Docker image from your local files through a web browser. Docker Desktop builds the image on your machine, then you upload it to Azure.

### How to install

**Option A — Winget (automatic, you already have it):**

```powershell
winget install Docker.DockerDesktop
```

Wait for it to finish, then **restart your computer**.

**Option B — Manual download:**

1. Go to https://www.docker.com/products/docker-desktop/
2. Click **Download for Windows - AMD64**
3. Run the installer
4. Restart your computer

### Verify it works

Open **PowerShell** and type:

```powershell
docker --version
```

You should see something like `Docker version 27.x.x, build xxxxx`.

---

## Step 2: Build the TimesFM Docker Image

This bakes the ~300 MB TimesFM model weights into the image so Azure doesn't have to download them every time the container starts.

### Get your HuggingFace token ready

You need your HuggingFace token (starts with `hf_`). If you don't have it:

1. Go to https://huggingface.co/settings/tokens
2. Click **New token** → name it `timesfm` → select **Read** role → **Create**
3. Copy the token (it starts with `hf_`)
4. Also visit https://huggingface.co/google/timesfm-2.5-200m-pytorch and click **Access repository** to accept the terms

### Build the image

Open **PowerShell** and run these commands **one at a time**:

```powershell
# Go to the service folder
cd "C:\Users\kusha\OneDrive\डेस्कटॉप\PROSPEKTLAB\timesfm-service"

# Build the image (replace hf_... with your actual token)
# This takes 10–20 minutes on first run because it downloads the model
docker build --build-arg HF_TOKEN=hf_your_actual_token_here -t timesfm:1.0.0 .
```

**What happens during the build:**
- Downloads Python packages (~2 min)
- Downloads TimesFM 2.5 200M model weights from HuggingFace (~5–10 min, ~300 MB)
- Bakes everything into the image

When you see `Successfully built` and `Successfully tagged timesfm:1.0.0`, you're done.

### Verify the build worked (optional, local test)

```powershell
# Run the container locally
docker run -d -p 8000:8000 --name timesfm-test -e HF_TOKEN=hf_your_actual_token_here timesfm:1.0.0

# Wait 30 seconds for the model to load inside the container, then test:
curl http://localhost:8000/health

# You should see: {"status":"ok","model_available":true,...}

# Stop the local test
docker stop timesfm-test
docker rm timesfm-test
```

---

## Step 3: Create Azure Container Registry (Portal)

This is where your Docker image will be stored in Azure, like a private warehouse.

1. Open your browser and go to **https://portal.azure.com**
2. Sign in with your Microsoft account (the one with your Azure subscription)
3. In the top search bar, type **Container registries** and click it
4. Click **+ Create** (big blue button)

### Basics tab

Fill in:

| Field | What to enter |
|-------|---------------|
| **Subscription** | Pick your subscription (usually there's only one) |
| **Resource group** | Click **Create new** → type `rg-timesfm` → click **OK** |
| **Registry name** | Type `acrtimesfm` followed by random numbers, e.g. `acrtimesfm482913`. This must be **globally unique** (no one else in the world can have this name). If it's taken, try another number. |
| **Location** | Pick **(US) East US** |
| **SKU** | Select **Standard** (Basic also works but Standard is more reliable) |

Click **Review + create** at the bottom, then click **Create**.

Wait for the deployment to finish (you'll see a spinning circle, takes about 1 minute). When you see **Your deployment is complete**, click **Go to resource**.

### Get your ACR credentials

You'll need these in Step 4 to push your image.

1. In the left sidebar of your registry, click **Access keys**
2. Click the toggle to **Enable** "Admin user" (this lets Docker log in with a username/password)
3. Note down these three values (copy-paste them somewhere safe):
   - **Login server**: e.g. `acrtimesfm482913.azurecr.io`
   - **Username**: same as your registry name, e.g. `acrtimesfm482913`
   - **password**: the long string shown (click the eye icon to reveal it)

---

## Step 4: Push Your Image to Azure

Now you upload the image from your laptop to the Azure registry you just created.

Open **PowerShell** and run these three commands (replace with YOUR actual values from Step 3):

```powershell
# 1. Log in to your Azure registry
# Replace acrtimesfm482913 with YOUR registry name
docker login acrtimesfm482913.azurecr.io -u acrtimesfm482913 -p "your_password_from_step_3"

# 2. Tag your local image for Azure
# (This creates a reference pointing to your Azure registry)
docker tag timesfm:1.0.0 acrtimesfm482913.azurecr.io/timesfm:1.0.0

# 3. Push (upload) the image
# This uploads ~1.5 GB, takes 2–5 minutes depending on your internet
docker push acrtimesfm482913.azurecr.io/timesfm:1.0.0
```

When you see `latest: digest: sha256:... size: ...`, the upload is complete.

---

## Step 5: Create Azure Container App (Portal)

This creates the live web service that runs your image and gives you a public HTTPS URL.

1. In **https://portal.azure.com**, use the top search bar to search **Container Apps**
2. Click **Container Apps** in the results, then click **+ Create**

### Basics tab

| Field | What to enter |
|-------|---------------|
| **Subscription** | Same as before |
| **Resource group** | Select `rg-timesfm` (the one you created) |
| **Container app name** | Type `timesfm-inference` |
| **Region** | **East US** (must match your registry location) |
| **Container Apps Environment** | Click **Create new** → name it `cae-timesfm` → click **Create** |

Click **Next: Container** (or the **Container** tab at the top).

### Container tab

| Field | What to enter |
|-------|---------------|
| **Use quickstart image** | **Uncheck** this box |
| **Image source** | Select **Azure Container Registry** |
| **Registry** | Select your registry (`acrtimesfm482913`) from the dropdown |
| **Image** | Select `timesfm` |
| **Image tag** | Select `1.0.0` |
| **CPU and memory** | Change to **2 cores** and **4 Gi** (TimesFM needs memory to load the model) |

Click **Next: Ingress** (or the **Ingress** tab).

### Ingress tab

| Field | What to enter |
|-------|---------------|
| **Ingress** | **Enable** (toggle ON) |
| **Ingress traffic** | Select **Accepting traffic from anywhere** |
| **Target port** | Type `8000` |

Click **Next: Environment variables** (or click **Review + create** if you don't see an Environment variables tab).

### Environment variables (if shown)

Click **+ Add** to add these two:

| Name | Source | Value / Secret reference |
|------|--------|--------------------------|
| `PORT` | Manual entry | `8000` |
| `MCP_PORT` | Manual entry | `8001` |

Then click **+ Add** again for the secret:

| Name | Source | Value |
|------|--------|-------|
| `HF_TOKEN` | **Secret reference** | (You'll add this as a secret below) |

**Wait — actually, Azure portal Container Apps UI may not show "Secret reference" in the same flow.** Let me give you the simpler path:

**Simpler approach for secrets:**

Instead of adding `HF_TOKEN` as an env var now, we'll add it as a **secret** after the app is created. The baked-in model weights mean the container doesn't strictly need `HF_TOKEN` at runtime (it only needed it during the Docker build). 

However, if you ever rebuild without baking, you'd need it. For safety, let's add it anyway:

1. Look for a **Secrets** section on this page (usually below Environment variables)
2. If you see it, click **+ Add**:
   - Secret name: `hf-token`
   - Secret value: your `hf_...` token
3. Then in Environment variables, add:
   - Name: `HF_TOKEN`
   - Value type: **Reference a secret**
   - Secret reference: `hf-token`

If you don't see a Secrets section here, don't worry — you can add it after deployment.

Click **Review + create**, then click **Create**.

Wait 2–3 minutes for deployment.

---

## Step 6: Get Your URL and Test

1. When deployment finishes, click **Go to resource**
2. At the top of the page, you'll see **Application URL**: something like
   ```
   https://timesfm-inference.xxxxxx.eastus.azurecontainerapps.io
   ```
3. **Copy this URL** — you'll need it in the next step

### Test it's working

Open PowerShell and run:

```powershell
# Replace with YOUR actual URL
curl https://timesfm-inference.xxxxxx.eastus.azurecontainerapps.io/health
```

You should see a JSON response like:
```json
{"status":"ok","model_available":true,"model_loaded":true}
```

If you get an error or timeout, wait 1–2 more minutes (the model takes time to load on first startup) and try again.

Test a forecast:

```powershell
curl -X POST https://timesfm-inference.xxxxxx.eastus.azurecontainerapps.io/forecast `
  -H "Content-Type: application/json" `
  -d '{"values":[120,128,135,142,151,158,167],"horizon":4}'
```

---

## Step 7: Connect Your Local Finagent Project

Now tell your local project to use the Azure service instead of loading the model on your laptop.

1. Open the file: `C:\Users\kusha\OneDrive\डेस्कटॉप\PROSPEKTLAB\finagent\.env`
2. Add this line at the bottom (replace with YOUR URL):

```bash
TIMESFM_REMOTE_URL=https://timesfm-inference.xxxxxx.eastus.azurecontainerapps.io
```

3. Save the file

From now on, whenever your local finagent runs a forecast, it will **automatically call Azure** instead of loading the 200M model into your laptop's RAM.

---

## Troubleshooting

### "docker build" fails with "Repository Not Found" or 401

- Your HuggingFace token is wrong, or you haven't accepted the model terms
- Fix: Visit https://huggingface.co/google/timesfm-2.5-200m-pytorch and click **Access repository**
- Get a fresh token from https://huggingface.co/settings/tokens

### Container keeps restarting in Azure

1. In the portal, go to your Container App
2. In the left sidebar, click **Monitoring** → **Log stream**
3. Look for red error messages
4. Most common causes:
   - **Out of memory**: Increase to 4 Gi (Step 5)
   - **Port mismatch**: Make sure Target port is `8000` (not 80 or 8080)
   - **Image not found**: Make sure you pushed to the correct registry and selected the right image tag

### "curl" times out

- The container is still starting up and loading the model into memory
- Wait 2–3 minutes after deployment, then try again

### Docker login fails

- Make sure you enabled **Admin user** in Step 3 (Access keys section of your registry)
- Double-check the password — copy it exactly, it's case-sensitive

### I can't find "Secret reference" in the portal

No problem. Since the model weights are baked into the image, `HF_TOKEN` isn't actually needed at runtime. You can skip adding it as a secret. The container will work fine without it.

---

## How Much Does This Cost?

| Service | Cost |
|---------|------|
| **Container Registry** (Standard) | ~$5/month |
| **Container App** (2 vCPU, 4 GiB) | ~$0.000024/vCPU/s + $0.000003/GiB/s while running. With 0 min replicas (scales to zero when idle), you pay almost nothing when not in use. Typical cost: **$5–20/month** with moderate use, **~$0** when idle. |
| **Data transfer** | First 5 GB/month is free, then ~$0.087/GB |

**To stop all costs immediately:** Delete the resource group `rg-timesfm` in the portal → it deletes everything at once.

---

## If You Want to Update the Code Later

1. Make code changes locally
2. Rebuild: `docker build --build-arg HF_TOKEN=hf_... -t timesfm:1.0.0 .`
3. Push again: `docker push acrtimesfm482913.azurecr.io/timesfm:1.0.0`
4. In the portal, go to your Container App → **Revision management** → **Create new revision** → select the updated image → **Create**

---

## Quick Reference: The 4 Docker Commands You Need

```powershell
# 1. Build
cd "C:\Users\kusha\OneDrive\डेस्कटॉप\PROSPEKTLAB\timesfm-service"
docker build --build-arg HF_TOKEN=hf_your_token -t timesfm:1.0.0 .

# 2. Login to Azure registry
docker login acrtimesfm482913.azurecr.io -u acrtimesfm482913 -p "your_password"

# 3. Tag
docker tag timesfm:1.0.0 acrtimesfm482913.azurecr.io/timesfm:1.0.0

# 4. Push
docker push acrtimesfm482913.azurecr.io/timesfm:1.0.0
```

Everything else is clicks in the Azure portal.
