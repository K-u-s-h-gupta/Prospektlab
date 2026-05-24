# TimesFM Azure Deployment — Choose Your Path

I built multiple deployment options for you. Since **Docker Desktop failed to install** on your laptop, here is the **recommended path** and all alternatives.

---

## RECOMMENDED: Azure Cloud Shell (Zero Local Installation)

**You don't need to install anything on your laptop.**  
Everything happens in Azure's free browser-based terminal.

### What you need
- Web browser
- Your Azure subscription (already have it)
- Your HuggingFace token

### Time required
- 5 minutes of copy-paste into Cloud Shell
- 15–20 minutes waiting for Azure to build the image
- Total hands-on time: **~5 minutes**

### Steps

1. **Open Cloud Shell**: https://shell.azure.com → Sign in → Select **PowerShell**

2. **Run the generator** on your laptop (creates the exact commands for you):
   ```powershell
   cd "C:\Users\kusha\OneDrive\डेस्कटॉप\PROSPEKTLAB\timesfm-service"
   .\cloud-shell-deploy.ps1 -HF_TOKEN "hf_your_actual_token"
   ```
   This prints a block of commands. **Copy them**.

3. **Upload the deploy package** to Cloud Shell:
   - In Cloud Shell toolbar, click **Upload** (paper icon)
   - Select `deploy-package.zip` from `PROSPEKTLAB/timesfm-service/`
   - In Cloud Shell terminal, run:
     ```powershell
     Expand-Archive -Path deploy-package.zip -DestinationPath timesfm-service -Force
     cd timesfm-service
     ```

4. **Paste the commands** from Step 2 into Cloud Shell and press Enter

5. **Wait 15–20 minutes** while Azure builds the image (downloads ~300MB model weights)

6. **Get your URL** — the last command prints:
   ```
   Your TimesFM API URL: https://timesfm-inference.xxx.eastus.azurecontainerapps.io
   ```

7. **Add to your local `.env`**:
   ```bash
   TIMESFM_REMOTE_URL=https://timesfm-inference.xxx.eastus.azurecontainerapps.io
   ```

**Full guide**: See `CLOUD-SHELL-DEPLOY.md` for detailed screenshots-level instructions.

---

## ALTERNATIVE 1: Azure Portal (Point-and-Click)

If you prefer clicking in the Azure web portal over typing commands:

**You still need Docker Desktop for 4 commands** to build and push the image.

But since Docker failed to install, this path is currently blocked for you.

**Full guide**: See `PORTAL-DEPLOYMENT.md`

---

## ALTERNATIVE 2: Local Docker (No Azure)

Run TimesFM only on your laptop, no cloud costs:

**Requires Docker Desktop** (which failed to install for you).

**Full guide**: See `PORTAL-DEPLOYMENT.md` → "Option C: Docker-Only Local Mode"

---

## ALTERNATIVE 3: Azure CLI + PowerShell Script (Requires Docker + AZ CLI)

For users who have both Docker and Azure CLI installed locally:

```powershell
cd timesfm-service
.\deploy-azure.ps1 -HF_TOKEN $env:HF_TOKEN
```

**Full guide**: See `DEPLOYMENT-GUIDE.md`

---

## What Was Built For You

| File | Purpose |
|------|---------|
| `timesfm-service/main.py` | FastAPI REST server (forecast + anomaly + health) |
| `timesfm-service/mcp_server.py` | MCP protocol server for finagent integration |
| `timesfm-service/Dockerfile` | Bakes TimesFM 200M model weights into the image |
| `timesfm-service/requirements.txt` | Minimal Python dependencies |
| `timesfm-service/deploy-package.zip` | **Ready-to-upload package for Cloud Shell** |
| `timesfm-service/cloud-shell-deploy.ps1` | Generates copy-paste commands for Cloud Shell |
| `timesfm-service/CLOUD-SHELL-DEPLOY.md` | Detailed Cloud Shell deployment guide |
| `timesfm-service/PORTAL-DEPLOYMENT.md` | Azure Portal point-and-click guide |
| `timesfm-service/DEPLOYMENT-GUIDE.md` | All deployment options overview |
| `timesfm-service/deploy-azure.ps1` | Automated Azure CLI deployment script |
| `timesfm-service/check-prerequisites.ps1` | Checks if your laptop is ready |
| `timesfm-service/README.md` | API documentation and quick start |
| `finagent/tools/mcp/forecasting.py` | **Modified** — auto-calls remote Azure endpoint |
| `finagent/.env.example` | Shows `TIMESFM_REMOTE_URL` variable |

---

## Important Reminders

### HuggingFace Token
- Get it: https://huggingface.co/settings/tokens (create a **Read** token)
- Accept model terms: https://huggingface.co/google/timesfm-2.5-200m-pytorch

### Cost
- **Container Registry**: ~$5/month
- **Container App**: ~$0 when idle (scales to zero), ~$5–20 with moderate use
- **Delete anytime**: `az group delete --name rg-timesfm --yes` in Cloud Shell

### After Deployment
Your local finagent project will **automatically** call the Azure endpoint instead of loading the 200M model locally. No code changes needed beyond adding `TIMESFM_REMOTE_URL` to `.env`.

---

## Need Help?

If any step fails, the most common issues are:
1. **Wrong HF token** → Create a new one and re-run
2. **Haven't accepted model terms** → Visit the HuggingFace model page
3. **App returns 503** → Wait 2–3 minutes, the model is still loading into memory

Open `CLOUD-SHELL-DEPLOY.md` for full troubleshooting.
