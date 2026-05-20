# Production Verification Checklist

After deploying the updated code to ECS and Amplify, verify the following:

## Backend (ECS) Verification

### 1. Health Check
```bash
# Should return 200 with {"status": "ok", "service": "oracle-fios"}
curl https://YOUR_ECS_BACKEND_URL/health
```

### 2. MCP Server Connectivity
```bash
# Should return {"all_ok": true, "servers": {...}}
curl https://YOUR_ECS_BACKEND_URL/api/health/mcp
```

If `all_ok` is `false`, check:
- MCP service URLs in ECS environment variables
- Security group rules allow internal traffic on ports 8001-8005
- MCP containers are running and healthy

### 3. Test Chat Endpoint (JSON)
```bash
curl -X POST https://YOUR_ECS_BACKEND_URL/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is RELIANCE?", "mode": "research"}'
```

Expected response:
```json
{
  "reply": "...",
  "agents_used": [...],
  "rich": {...}
}
```

### 4. Test Streaming Chat Endpoint
```bash
curl -N -X POST https://YOUR_ECS_BACKEND_URL/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "What is TCS?", "mode": "research"}'
```

Expected: Server-Sent Events stream with events like:
```
event: agent_event
data: {...}

event: final
data: {"type":"final","reply":"...","agents_used":[...],...}
```

### 5. CORS Header Validation
```bash
curl -H "Origin: https://YOUR_AMPLIFY_DOMAIN" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: Content-Type" \
  -X OPTIONS https://YOUR_ECS_BACKEND_URL/api/chat/stream -v
```

Response should include:
```
Access-Control-Allow-Origin: https://YOUR_AMPLIFY_DOMAIN
Access-Control-Allow-Methods: *
Access-Control-Allow-Headers: *
```

---

## Frontend (Amplify) Verification

### 1. Load Amplify App
Open `https://YOUR_AMPLIFY_DOMAIN` in a browser.

### 2. Check Backend URL
Open DevTools Console and run:
```javascript
console.log("API_BASE:", window.__BACKEND_URL || localStorage.getItem("backendUrl") || "relative");
```

Should print your ECS backend URL or "relative" for local dev.

### 3. Test Chat Request
In DevTools Console:
```javascript
fetch(window.__BACKEND_URL ? (window.__BACKEND_URL + "/api/chat") : "/api/chat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ message: "Test", response_depth: "deep" })
})
.then(r => r.json())
.then(data => console.log("Response:", data))
.catch(e => console.error("Error:", e));
```

Should return a valid chat response.

### 4. Test Streaming
In DevTools Console:
```javascript
const url = window.__BACKEND_URL ? (window.__BACKEND_URL + "/api/chat/stream") : "/api/chat/stream";
const es = new EventSource(url, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ message: "Test streaming", response_depth: "deep" })
});
es.onmessage = (e) => console.log("Event:", e.data);
es.onerror = (e) => console.error("Error:", e);
// Close after a few seconds: es.close();
```

Should receive multiple SSE events including a "final" event.

---

## Network Verification

### 1. Ensure ECS Task Can Reach MCP Servers
SSH into ECS task or run a one-off task:
```bash
curl http://MCP_NSE_INDIA_URL/health
curl http://MCP_FUNDAMENTALS_URL/health
curl http://MCP_RESEARCH_URL/health
curl http://MCP_DOCS_URL/health
curl http://MCP_VALUATION_URL/health
```

All should return 200 OK.

### 2. Amplify Can Reach ECS Backend
From your local machine:
```bash
curl https://YOUR_ECS_BACKEND_URL/health
```

Should return 200 OK.

### 3. Check Security Groups
**ECS Security Group:**
- Inbound: Allow 8080 from Amplify (or ALB/API Gateway)
- Outbound: Allow 8001-8005 to MCP services (or MCP security group)

**MCP Security Group:**
- Inbound: Allow 8001-8005 from ECS security group

---

## Environment Variables Confirmation

### ECS Task Definition
Verify these are set:
```
CORS_ORIGINS=https://YOUR_AMPLIFY_DOMAIN
MCP_NSE_INDIA_URL=http://MCP_NSE_SERVICE_NAME:8001/mcp
MCP_FUNDAMENTALS_URL=http://MCP_FUNDAMENTALS_SERVICE_NAME:8002/mcp
MCP_RESEARCH_URL=http://MCP_RESEARCH_SERVICE_NAME:8003/mcp
MCP_DOCS_URL=http://MCP_DOCS_SERVICE_NAME:8004/mcp
MCP_VALUATION_URL=http://MCP_VALUATION_SERVICE_NAME:8005/mcp
OPENAI_API_KEY=your-key
```

### Amplify Build Settings
Verify backend URL is injected into HTML or set as environment variable.

---

## CloudWatch Logs

Monitor these for errors:

1. **Backend logs** (ECS task):
   ```
   oracle.api - ERROR - CORS error
   oracle.api - ERROR - Agent error
   oracle.api - WARNING - MCP server unavailable
   ```

2. **MCP server logs**:
   ```
   Connection refused
   Timeout
   HTTP 5xx
   ```

3. **Frontend errors** (browser console):
   ```
   Fetch failed
   CORS policy
   API_BASE undefined
   ```

---

## If Agent Is Still Not Working

### Step 1: Verify Backend Is Running
```bash
curl https://YOUR_ECS_BACKEND_URL/health
```

### Step 2: Check MCP Connectivity
```bash
curl https://YOUR_ECS_BACKEND_URL/api/health/mcp
```

If any server shows `"ok": false`:
- Check the `error` field for connection details
- Verify environment variables are correct
- Restart MCP services or ECS task

### Step 3: Test Chat Without MCP
Try a simple test in ECS task shell:
```python
from Backend.api import app
from fastapi.testclient import TestClient
client = TestClient(app)
response = client.post("/api/chat", json={"message": "test", "mode": "research"})
print(response.status_code, response.json())
```

If 500 error, check the exception in logs.

### Step 4: Check Frontend Logs
In browser DevTools → Network tab:
- Verify `/api/chat/stream` returns 200 and streams events
- Check response headers for `Access-Control-Allow-Origin`
- Look for CORS or timeout errors

### Step 5: Manual MCP Health Check
Run this from inside ECS task to verify each MCP endpoint:
```python
import httpx
for name, url in [
	("nse", "http://127.0.0.1:8001/health"),
	("fundamentals", "http://127.0.0.1:8002/health"),
	("research", "http://127.0.0.1:8003/health"),
	("docs", "http://127.0.0.1:8004/health"),
	("valuation", "http://127.0.0.1:8005/health"),
]:
	try:
		r = httpx.get(url, timeout=2)
		print(f"{name}: {r.status_code}")
	except Exception as e:
		print(f"{name}: ERROR - {e}")
```

---

## Common Issues & Fixes

| Issue | Check | Fix |
|-------|-------|-----|
| CORS error in browser | `CORS_ORIGINS` env var | Add Amplify domain to env var |
| Agent times out | MCP server health | Restart MCP containers in ECS |
| "Message cannot be empty" | Check fetch payload | Ensure `message` field is not empty |
| 500 error on `/api/chat` | CloudWatch logs | Check for missing imports or OpenAI API key |
| EventSource connection fails | CORS headers | Verify `Access-Control-Allow-Origin` includes frontend domain |
| MCP returns 503 | MCP service status | Check ECS logs for MCP startup errors |

---

## Performance Optimization

If agent responses are slow:

1. **Increase ECS task resources** (CPU/memory)
2. **Increase `GRAPH_RUN_TIMEOUT_SECONDS`** if queries time out legitimately
3. **Check MCP server latency**: `/api/health/mcp` returns latency_ms for each
4. **Profile the agent**: Add timing logs in `Backend/api.py` `_stream_graph_run()`

---

## Rollback Plan

If the deployment breaks production:

1. **Immediate:** Revert to previous ECS task definition
2. **Check:** Verify MCP servers are still running
3. **Debug:** Review CloudWatch logs for what broke
4. **Fix:** Apply patches and redeploy

---

## Support

For questions, check:
1. `/PRODUCTION_DEPLOYMENT_GUIDE.md` — Configuration instructions
2. CloudWatch logs — Real error messages
3. Browser console — Frontend connection issues
4. `Backend/api.py` line 602-687 — API endpoints and error handling
