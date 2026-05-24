# TimesFM 2.5 200M — Standalone Inference Service

A lightweight, containerized microservice that exposes **TimesFM 2.5 200M** time-series forecasting over HTTP.

- **REST API** on port `8000` — plain JSON endpoints, easy to call from any client.
- **MCP Server** on port `8001` — `fastmcp` streamable-http transport for integration with MCP clients (e.g. finagent).
- **Model weights baked into the Docker image** — no runtime download penalty.

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Service metadata |
| GET | `/health` | Health / readiness probe |
| POST | `/forecast` | Zero-shot forecast with quantile bands |
| POST | `/anomaly` | Anomaly detection vs P10–P90 corridor |

### POST /forecast

```json
{
  "values": [120.0, 128.5, 135.2, 142.0, 150.8, 158.3, 167.1],
  "horizon": 4,
  "freq": 1,
  "quantiles": [0.1, 0.5, 0.9]
}
```

Response:

```json
{
  "point_forecast": [175.2, 182.5, 190.1, 197.8],
  "quantile_forecasts": {
    "0.1": [170.1, 177.0, 184.2, 191.5],
    "0.5": [175.2, 182.5, 190.1, 197.8],
    "0.9": [180.5, 188.2, 196.0, 204.1]
  },
  "horizon": 4,
  "freq": 1,
  "model_used": "timesfm_2.5",
  "metadata": {"input_length": 7, "api": "v2.5"}
}
```

### POST /anomaly

```json
{
  "historical": [120.0, 128.5, 135.2, 142.0, 150.8, 158.3, 167.1],
  "new_values": [200.0, 170.0],
  "freq": 1
}
```

---

## Quick Start (Local Docker)

```powershell
# 1. Build image (bakes ~300 MB model weights)
cd timesfm-service
docker build --build-arg HF_TOKEN=$env:HF_TOKEN -t timesfm:local .

# 2. Run REST server
docker run -p 8000:8000 -e HF_TOKEN=$env:HF_TOKEN timesfm:local

# 3. Test
curl http://localhost:8000/health
curl -X POST http://localhost:8000/forecast `
  -H "Content-Type: application/json" `
  -d '{"values":[120,128,135,142,151,158,167],"horizon":4}'
```

---

## Deploy to Azure Container Apps

```powershell
# One-click deployment (requires az CLI + Docker)
cd timesfm-service
.\deploy-azure.ps1 -HF_TOKEN $env:HF_TOKEN
```

The script will:
1. Create resource group `rg-timesfm` in `eastus`
2. Create Azure Container Registry `acrtimesfm...`
3. Build image in ACR (model baked at build time)
4. Create Container Apps environment
5. Deploy the app with 2 vCPU / 4 GiB memory
6. Print the public HTTPS endpoint

After deployment, copy the printed `TIMESFM_REMOTE_URL` into your local `.env`:

```
TIMESFM_REMOTE_URL=https://timesfm-inference.xxx.eastus.azurecontainerapps.io
```

Your local finagent project will **automatically** route TimesFM inference to the remote service instead of loading the model locally.

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `HF_TOKEN` | — | HuggingFace token (gated model download) |
| `PORT` | `8000` | REST server port |
| `MCP_PORT` | `8001` | MCP server port |

---

## Files

| File | Purpose |
|------|---------|
| `main.py` | FastAPI REST server |
| `mcp_server.py` | FastMCP streamable-http server |
| `Dockerfile` | Multi-stage build with baked model weights |
| `requirements.txt` | Minimal Python dependencies |
| `deploy-azure.ps1` | Azure CLI deployment script |
