# Production Deployment Guide — AWS ECS + Amplify

## Summary of Changes

The codebase has been updated to support production deployment on AWS ECS and Amplify. All hardcoded `localhost` references have been replaced with environment-driven configuration.

---

## Backend (ECS) Configuration

### 1. CORS Configuration
**File:** `Backend/api.py`

The backend now reads allowed CORS origins from the `CORS_ORIGINS` environment variable instead of hardcoding `localhost:3000`.

**ECS Environment Variable:**
```bash
CORS_ORIGINS=https://your-amplify-domain.amplifyapp.com,https://your-custom-domain.com
```

**Development Fallback:**
```bash
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

### 2. MCP Server URLs
**File:** `finagent/tools/mcp_config.py`

MCP servers (NSE, Fundamentals, Research, Docs, Valuation) now use environment variables instead of `127.0.0.1` hardcoded URLs.

**ECS Environment Variables:**
```bash
MCP_NSE_INDIA_URL=http://mcp-nse-service:8001/mcp
MCP_FUNDAMENTALS_URL=http://mcp-fundamentals-service:8002/mcp
MCP_RESEARCH_URL=http://mcp-research-service:8003/mcp
MCP_DOCS_URL=http://mcp-docs-service:8004/mcp
MCP_VALUATION_URL=http://mcp-valuation-service:8005/mcp
```

**Local Development Fallback:**
```bash
MCP_NSE_INDIA_URL=http://127.0.0.1:8001/mcp
MCP_FUNDAMENTALS_URL=http://127.0.0.1:8002/mcp
MCP_RESEARCH_URL=http://127.0.0.1:8003/mcp
MCP_DOCS_URL=http://127.0.0.1:8004/mcp
MCP_VALUATION_URL=http://127.0.0.1:8005/mcp
```

### 3. Real Agent Loop Integration
**File:** `finagent/api.py`

The `/api/chat` and `/api/chat/stream` endpoints now invoke the real agent loop instead of returning placeholder responses.

- `/api/chat` — Returns JSON response with agent results
- `/api/chat/stream` — Streams agent events via Server-Sent Events (SSE)

Both endpoints properly handle exceptions and log errors.

---

## Frontend (Amplify) Configuration

### 1. Backend URL Routing
**File:** `finagent/gateway/widget.html`

The frontend widget now supports three ways to specify the backend API base URL:

**Priority Order:**
1. **JavaScript variable:** `window.__BACKEND_URL` (if injected by Amplify hosting)
2. **LocalStorage:** `localStorage.getItem("backendUrl")` (if set by user/script)
3. **Hostname detection:** Falls back to API Gateway URL for Amplify domains, or relative paths for local dev

**Amplify Deployment:**
In Amplify hosting build settings, inject the backend URL into HTML:
```html
<script>
  window.__BACKEND_URL = "https://your-ecs-backend-domain.com";
</script>
```

Or in `amplify.yml`:
```yaml
frontend:
  build:
	commands:
	  - echo "window.__BACKEND_URL='$BACKEND_URL';" > public/config.js
```

---

## ECS Deployment Checklist

### 1. Update Environment Variables in ECS Task Definition
```json
{
  "name": "CORS_ORIGINS",
  "value": "https://your-amplify-domain.amplifyapp.com"
},
{
  "name": "MCP_NSE_INDIA_URL",
  "value": "http://mcp-nse-service:8001/mcp"
},
{
  "name": "MCP_FUNDAMENTALS_URL",
  "value": "http://mcp-fundamentals-service:8002/mcp"
},
{
  "name": "MCP_RESEARCH_URL",
  "value": "http://mcp-research-service:8003/mcp"
},
{
  "name": "MCP_DOCS_URL",
  "value": "http://mcp-docs-service:8004/mcp"
},
{
  "name": "MCP_VALUATION_URL",
  "value": "http://mcp-valuation-service:8005/mcp"
},
{
  "name": "OPENAI_API_KEY",
  "value": "your-key-here"
}
```

### 2. Verify MCP Services Are Reachable
Ensure all MCP services (8001-8005) are:
- Running and accessible from the backend task
- Using service discovery (e.g., ECS service names) or fixed internal IPs
- Not requiring changes to security groups/network policies

### 3. Test Health Endpoint
```bash
curl https://your-ecs-backend/health
# Expected: {"status": "ok", "service": "oracle-fios"}
```

### 4. Test MCP Health Endpoint
```bash
curl https://your-ecs-backend/api/health/mcp
# Expected: {"all_ok": true, "servers": {...}}
```

---

## Amplify Deployment Checklist

### 1. Inject Backend URL into Frontend
In Amplify Console → Build settings → Build commands:
```bash
npm run build && echo 'window.__BACKEND_URL="'$BACKEND_API_URL'";' >> build/index.html
```

Or create a `.env.production` file:
```
REACT_APP_API_BASE=https://your-ecs-backend-domain.com
```

### 2. Configure API Gateway / Load Balancer
If using an API Gateway in front of ECS:
- Ensure CORS headers are properly forwarded
- Verify `/api/*` routes point to the ECS backend

### 3. Test Frontend Connectivity
Open the Amplify app in browser → Open DevTools Console:
```javascript
console.log(window.__BACKEND_URL || localStorage.getItem("backendUrl"));
// Should print your backend URL
```

---

## Local Development

### 1. Backend (localhost)
```bash
# Backend/.env or environment
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
MCP_NSE_INDIA_URL=http://127.0.0.1:8001/mcp
MCP_FUNDAMENTALS_URL=http://127.0.0.1:8002/mcp
MCP_RESEARCH_URL=http://127.0.0.1:8003/mcp
MCP_DOCS_URL=http://127.0.0.1:8004/mcp
MCP_VALUATION_URL=http://127.0.0.1:8005/mcp

# Start backend
uvicorn api:app --host 0.0.0.0 --port 8080
```

### 2. MCP Servers (localhost)
```bash
# Terminal 1: NSE MCP
python Backend/mcp_servers/nse_server.py

# Terminal 2: Fundamentals MCP
python Backend/mcp_servers/fundamentals_server.py

# Terminal 3: Research MCP
python Backend/mcp_servers/research_server.py

# Terminal 4: Docs MCP
python Backend/mcp_servers/docs_server.py

# Terminal 5: Valuation MCP
python Backend/mcp_servers/mcp_valuation.py
```

### 3. Frontend (localhost)
Amplify/Next.js app will auto-detect localhost and use relative paths (no backend URL needed).

---

## Troubleshooting

### CORS Errors
**Error:** `Access to XMLHttpRequest blocked by CORS policy`

**Solution:**
1. Check the `CORS_ORIGINS` environment variable on the backend
2. Ensure the Amplify domain matches one of the origins
3. Test with: `curl -H "Origin: https://your-amplify-domain" https://your-backend/api/health`

### MCP Servers Down
**Error:** Agent runs fail, `/api/health/mcp` shows `all_ok: false`

**Solution:**
1. Verify MCP service URLs in ECS environment variables
2. Check ECS security groups allow internal traffic on ports 8001-8005
3. Test connectivity: `curl http://mcp-nse-service:8001/health` (from inside ECS task)

### Agent Timeout
**Error:** `The analysis stalled for too long and timed out`

**Solution:**
1. Increase `GRAPH_RUN_TIMEOUT_SECONDS` in `Backend/api.py` (default: 240s)
2. Ensure MCP servers are not timing out
3. Check ECS task CPU/memory is sufficient

### Frontend Blank / Not Loading
**Error:** Frontend loads but no chat response

**Solution:**
1. Check browser console for network errors
2. Verify `window.__BACKEND_URL` is set correctly
3. Test `/api/health` from frontend: `fetch(API_BASE + '/api/health')`

---

## Files Modified

1. **Backend/api.py** — Added CORS_ORIGINS environment variable support
2. **finagent/tools/mcp_config.py** — Made MCP URLs environment-driven
3. **finagent/api.py** — Integrated real agent loop, removed placeholders
4. **finagent/gateway/widget.html** — Added backend URL override support

---

## Next Steps

1. **Test locally** with the new environment variables
2. **Deploy to ECS** with correct environment configuration
3. **Deploy to Amplify** with backend URL injection
4. **Monitor** `/api/health` and `/api/health/mcp` endpoints for production issues
5. **Set up alerts** for:
   - MCP server connectivity failures
   - CORS errors in CloudWatch logs
   - High latency on `/api/chat/stream` endpoint

---

## References

- [FastAPI CORS Documentation](https://fastapi.tiangolo.com/tutorial/cors/)
- [AWS ECS Environment Variables](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definition_parameters.html)
- [AWS Amplify Environment Variables](https://docs.aws.amazon.com/amplify/latest/userguide/environment-variables.html)
- [Server-Sent Events (SSE) API](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
