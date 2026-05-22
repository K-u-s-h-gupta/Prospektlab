# 🔌 ProspektLab Complete API Reference

**Version:** 2.0.0  
**Last Updated:** May 21, 2026  
**Base URL:** `http://localhost:8000` (dev) | `https://api.prospektlab.com` (prod)

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Chat Endpoints](#chat-endpoints)
4. [Research Endpoints](#research-endpoints)
5. [Session Management](#session-management)
6. [Error Handling](#error-handling)
7. [Rate Limiting](#rate-limiting)
8. [Data Models](#data-models)
9. [Code Examples](#code-examples)
10. [WebSocket / SSE](#websocket--sse)

---

## Overview

### API Versions

| Endpoint | Version | Module | Status |
|----------|---------|--------|--------|
| `/api/chat` | v1 | Backend/api.py | Production |
| `/api/chat` | v2 | finagent/api.py | Production |
| `/api/research` | v1 | finagent/gateway/run.py | Experimental |
| `/api/stream` | v1 | finagent/api.py | Experimental |

### Response Format

All responses are JSON (unless SSE streaming):

```json
{
  "reply": "string",
  "agents_used": ["string"],
  "rich": {
	"type": "object",
	"chart": {
	  "type": "candlestick|line|bar|gauge",
	  "data": {}
	},
	"table": {},
	"text": "string"
  },
  "output_mode": "string",
  "response_depth": "string"
}
```

---

## Authentication

### API Key Authentication (Future)

Currently not required, but planned:

```
Authorization: Bearer {API_KEY}
X-API-Key: {API_KEY}
```

### CORS Headers

Your API respects CORS. Allowed origins configured via `CORS_ORIGINS` env var:

```
Access-Control-Allow-Origin: https://app.prospektlab.com
Access-Control-Allow-Credentials: true
Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS
Access-Control-Allow-Headers: Content-Type, Authorization
```

### Current Security Model

- **Open API** for development
- **CORS-gated** in production
- **Rate limiting** via sliding window
- **No API key** currently required (auth stub in gateway)

---

## Chat Endpoints

### 1. POST `/api/chat` — Quick Chat

**Purpose:** Get immediate answer to a query  
**Module:** Backend/api.py (ORACLE FIOS)  
**Response Time:** 5-15 seconds

#### Request

```http
POST /api/chat HTTP/1.1
Host: api.prospektlab.com
Content-Type: application/json

{
  "message": "What is TCS's dividend yield?",
  "mode": "research"
}
```

#### Request Schema

```python
class ChatRequest(BaseModel):
	message: str                                    # Required
	mode: str = Field(default="research", 
					  pattern="^(research|marathon)$")  # Optional
```

#### Response (Success)

```http
HTTP/1.1 200 OK
Content-Type: application/json
Transfer-Encoding: chunked

{
  "reply": "TCS (Tata Consultancy Services) has a dividend yield of 1.85%, with the last dividend being ₹6.50 per share as of the current fiscal year.",
  "agents_used": [
	"fundamentals_agent",
	"nse_agent"
  ],
  "rich": {
	"gauge_chart": {
	  "type": "gauge",
	  "value": 1.85,
	  "min": 0,
	  "max": 5,
	  "title": "Dividend Yield (%)",
	  "color": "green"
	},
	"table": {
	  "headers": ["Metric", "Value"],
	  "rows": [
		["Dividend Yield", "1.85%"],
		["Last Dividend", "₹6.50"],
		["Payout Ratio", "45%"]
	  ]
	},
	"text": "TCS has maintained consistent dividend payments..."
  },
  "output_mode": "narrative",
  "response_depth": "standard"
}
```

#### Response Schema

```python
class ChatResponse(BaseModel):
	reply: str                                      # Main text response
	agents_used: list[str] = Field(default_factory=list)  # Which agents ran
	rich: dict[str, Any] | None = None             # Rich formatting
	output_mode: str | None = None                 # How response was formatted
	response_depth: str | None = None              # Actual depth used
```

#### Response (Streaming SSE)

```
event: message_start
data: {"session_id": "abc-123", "timestamp": "2026-05-21T10:30:00Z"}

event: agent_start
data: {"agent": "fundamentals_agent", "task": "Fetching TCS fundamentals..."}

event: agent_complete
data: {"agent": "fundamentals_agent", "result": {...}}

event: message_complete
data: {
  "reply": "TCS dividend yield is 1.85%",
  "agents_used": ["fundamentals_agent"],
  "rich": {...}
}
```

#### Possible Errors

```json
{
  "detail": "OpenAI authentication failed. Check the OPENAI_API_KEY configured for the backend."
}
```

```json
{
  "detail": "Rate limit exceeded. Max 100 requests per minute."
}
```

#### Examples

**cURL:**
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
	"message": "What is TCS dividend yield?",
	"mode": "research"
  }'
```

**Python (requests):**
```python
import requests

response = requests.post(
	"http://localhost:8000/api/chat",
	json={
		"message": "What is TCS dividend yield?",
		"mode": "research"
	}
)
print(response.json())
```

**Python (httpx async):**
```python
import httpx

async with httpx.AsyncClient() as client:
	response = await client.post(
		"http://localhost:8000/api/chat",
		json={
			"message": "What is TCS dividend yield?",
			"mode": "research"
		}
	)
	print(response.json())
```

**JavaScript (fetch):**
```javascript
const response = await fetch('/api/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
	message: 'What is TCS dividend yield?',
	mode: 'research'
  })
});
const data = await response.json();
console.log(data);
```

**JavaScript (SSE streaming):**
```javascript
const eventSource = new EventSource('/api/chat?stream=true&message=...');

eventSource.addEventListener('message_start', (e) => {
  const data = JSON.parse(e.data);
  console.log('Session:', data.session_id);
});

eventSource.addEventListener('agent_start', (e) => {
  const data = JSON.parse(e.data);
  console.log('Agent:', data.agent);
});

eventSource.addEventListener('message_complete', (e) => {
  const data = JSON.parse(e.data);
  console.log('Reply:', data.reply);
  eventSource.close();
});
```

---

### 2. POST `/api/stream` — Stream Chat Response

**Purpose:** Chat with real-time message streaming  
**Module:** finagent/api.py  
**Response Format:** Server-Sent Events (SSE)  
**Response Time:** 5-15 seconds

#### Request

```http
POST /api/stream HTTP/1.1
Host: api.prospektlab.com
Content-Type: application/json

{
  "message": "Compare TCS and Infosys",
  "response_depth": "deep"
}
```

#### Request Schema

```python
class ChatRequest(BaseModel):
	message: str
	response_depth: str = "deep"  # chat | standard | deep | marathon
```

#### Response (Streaming)

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive

event: stream_start
data: {"message_id": "uuid-123", "timestamp": "2026-05-21T10:30:00Z"}

event: thinking
data: {"text": "Comparing revenue growth, margins, ROE..."}

event: message
data: {"chunk": "TCS shows stronger margin", "tokens": 5}

event: message
data: {"chunk": " expansion compared to", "tokens": 4}

event: message
data: {"chunk": " Infosys.", "tokens": 2}

event: rich_object
data: {
  "type": "table",
  "headers": ["Metric", "TCS", "Infosys"],
  "rows": [...]
}

event: agents
data: {"agents_used": ["fundamentals_agent", "research_agent"]}

event: stream_complete
data: {"total_tokens": 245, "processing_time_ms": 8500}
```

#### Examples

**JavaScript (EventSource):**
```javascript
const eventSource = new EventSource('/api/stream?message=Compare%20TCS%20Infosys');

eventSource.addEventListener('stream_start', (e) => {
  console.log('Stream started:', JSON.parse(e.data));
});

eventSource.addEventListener('message', (e) => {
  const chunk = JSON.parse(e.data);
  document.getElementById('response').textContent += chunk.chunk;
});

eventSource.addEventListener('rich_object', (e) => {
  const table = JSON.parse(e.data);
  renderTable(table);
});

eventSource.addEventListener('stream_complete', (e) => {
  console.log('Done!', JSON.parse(e.data));
  eventSource.close();
});
```

**Python (httpx with streaming):**
```python
import httpx
import json

async with httpx.AsyncClient() as client:
	async with client.stream(
		"POST",
		"http://localhost:8000/api/stream",
		json={"message": "Compare TCS Infosys"}
	) as response:
		async for line in response.aiter_lines():
			if line.startswith('data: '):
				data = json.loads(line[6:])
				print(data)
```

---

## Research Endpoints

### 3. POST `/api/research` — Start Deep Research

**Purpose:** Initiate long-running deep company analysis  
**Module:** finagent/gateway/run.py  
**Response Time:** 2-5 minutes  
**Streaming:** SSE via `/api/session/{session_id}/events`

#### Request

```http
POST /api/research HTTP/1.1
Host: api.prospektlab.com
Content-Type: application/json

{
  "query": "Deep analysis of Asian Paints",
  "depth": "deep"
}
```

#### Request Schema

```python
class ResearchRequest(BaseModel):
	query: str                          # What to research
	depth: str = "deep"                 # chat | standard | deep | marathon
	target: str | None = None           # Specific ticker (optional, auto-extracted)
```

#### Response (Immediate)

```http
HTTP/1.1 202 Accepted
Content-Type: application/json

{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "created_at": "2026-05-21T10:30:00Z",
  "query": "Deep analysis of Asian Paints",
  "depth": "deep",
  "events_url": "/api/session/550e8400-e29b-41d4-a716-446655440000/events"
}
```

#### Response Schema

```python
class ResearchResponse(BaseModel):
	session_id: str                     # UUID
	status: str                         # running | complete | failed
	created_at: datetime
	query: str
	depth: str
	events_url: str                     # Where to subscribe for events
	progress: float = 0.0               # 0-100%
```

#### Polling Session Status

```http
GET /api/session/550e8400-e29b-41d4-a716-446655440000/status HTTP/1.1
Host: api.prospektlab.com

---

HTTP/1.1 200 OK
Content-Type: application/json

{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "progress": 65,
  "current_phase": "specialist_analysis",
  "phases_complete": ["identify", "enrichment", "breadth_survey", "deep_dive"],
  "estimated_time_remaining_seconds": 95
}
```

#### Examples

**Python:**
```python
import httpx
import json

async def start_research():
	async with httpx.AsyncClient() as client:
		# Start research
		response = await client.post(
			"http://localhost:8000/api/research",
			json={
				"query": "Analyze Asian Paints",
				"depth": "deep"
			}
		)
		session = response.json()
		session_id = session['session_id']

		# Subscribe to events
		async with client.stream(
			"GET",
			f"http://localhost:8000/api/session/{session_id}/events"
		) as event_response:
			async for line in event_response.aiter_lines():
				if line.startswith('data: '):
					event = json.loads(line[6:])
					print(f"Phase: {event.get('phase')}, Progress: {event.get('progress')}%")

asyncio.run(start_research())
```

**JavaScript:**
```javascript
async function startResearch() {
  // Start research
  const response = await fetch('/api/research', {
	method: 'POST',
	body: JSON.stringify({
	  query: 'Analyze Asian Paints',
	  depth: 'deep'
	})
  });

  const session = await response.json();
  const sessionId = session.session_id;

  // Subscribe to events
  const eventSource = new EventSource(`/api/session/${sessionId}/events`);

  eventSource.addEventListener('phase_start', (e) => {
	const data = JSON.parse(e.data);
	console.log(`Phase: ${data.phase}`);
  });

  eventSource.addEventListener('research_complete', (e) => {
	const data = JSON.parse(e.data);
	console.log(`Memo available at: ${data.memo_url}`);
	eventSource.close();
  });
}
```

---

## Session Management

### 4. GET `/api/session/{session_id}/events` — Subscribe to Events

**Purpose:** Real-time research session events (SSE)  
**Module:** finagent/gateway/run.py

#### Response (Streaming)

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache

event: phase_start
data: {
  "phase": "identify",
  "progress": 5,
  "description": "Resolving entity..."
}

event: phase_complete
data: {
  "phase": "identify",
  "progress": 10,
  "result": {
	"ticker": "ASIANPAINT",
	"exchange": "NSE"
  }
}

event: enrichment_progress
data: {
  "sub_phase": "fetching_india_snapshot",
  "progress": 20
}

...

event: research_complete
data: {
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "memo_url": "/memos/550e8400-e29b-41d4-a716-446655440000.md",
  "summary": "Asian Paints is the leading paint company...",
  "quality_score": 84,
  "total_time_seconds": 245,
  "sources_used": 52,
  "facts_verified": 28
}
```

#### Event Types

| Event | Data |
|-------|------|
| `phase_start` | phase, progress, description |
| `phase_complete` | phase, progress, result |
| `enrichment_progress` | sub_phase, progress |
| `specialist_analysis` | specialist_type, result |
| `verification_result` | claims_verified, red_flags |
| `research_complete` | memo_url, quality_score, time |
| `research_error` | error, phase, recovery |

---

### 5. GET `/api/session/{session_id}/status` — Get Session Status

**Purpose:** Poll current session status

#### Response

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "complete",
  "progress": 100,
  "current_phase": "synthesis",
  "phases_complete": [
	"identify",
	"enrichment",
	"breadth_survey",
	"deep_dive",
	"analysis",
	"specialist_analysis",
	"verification",
	"synthesis"
  ],
  "total_time_seconds": 245,
  "result": {
	"memo_url": "/memos/550e8400-e29b-41d4-a716-446655440000.md",
	"quality_score": 84
  }
}
```

---

### 6. GET `/api/session/{session_id}/memo` — Get Research Memo

**Purpose:** Retrieve generated research memo

#### Response

```http
HTTP/1.1 200 OK
Content-Type: text/markdown

# Asian Paints Deep Analysis

## Executive Summary

Asian Paints Limited is the leading decorative paint company in India...

## Financial Overview

### Key Metrics
- **Market Cap:** ₹2.1 trillion
- **PE Ratio:** 42.5x
- **ROE:** 18.2%
- **Dividend Yield:** 1.85%

## Valuation Analysis

### DCF Model
- Fair Value: ₹3,200-3,400

[... full memo ...]

## References

1. [NSE India - ASIANPAINT](https://www.nseindia.com/)
2. [Indian Paint Industry Report](...)
```

---

## Error Handling

### Standard Error Response

```json
{
  "detail": "Error message here",
  "type": "error_type",
  "status_code": 400,
  "timestamp": "2026-05-21T10:30:00Z"
}
```

### Common Errors

#### 400 Bad Request
```json
{
  "detail": "Invalid query: message cannot be empty",
  "type": "validation_error"
}
```

#### 401 Unauthorized
```json
{
  "detail": "OpenAI authentication failed. Check OPENAI_API_KEY.",
  "type": "authentication_error"
}
```

#### 429 Too Many Requests
```json
{
  "detail": "Rate limit exceeded: 100 requests per minute",
  "type": "rate_limit_error",
  "retry_after_seconds": 30
}
```

#### 500 Internal Server Error
```json
{
  "detail": "Internal server error: Connection timeout to MCP service",
  "type": "server_error"
}
```

#### 503 Service Unavailable
```json
{
  "detail": "MCP Fundamentals service unavailable (port 8002)",
  "type": "service_unavailable"
}
```

### Error Handling Best Practices

```python
import httpx
import time

async def resilient_chat_call(message: str, max_retries: int = 3):
	for attempt in range(max_retries):
		try:
			async with httpx.AsyncClient() as client:
				response = await client.post(
					"http://localhost:8000/api/chat",
					json={"message": message},
					timeout=30.0
				)
				response.raise_for_status()
				return response.json()

		except httpx.HTTPStatusError as e:
			if e.response.status_code == 429:
				# Rate limit: wait and retry
				wait_time = int(e.response.headers.get('retry-after', 60))
				print(f"Rate limited. Waiting {wait_time}s...")
				await asyncio.sleep(wait_time)
				continue
			elif e.response.status_code == 503:
				# Service unavailable: wait and retry
				print(f"Service unavailable. Retrying in 5s...")
				await asyncio.sleep(5)
				continue
			else:
				raise

		except httpx.TimeoutException:
			print(f"Timeout on attempt {attempt + 1}/{max_retries}")
			if attempt < max_retries - 1:
				await asyncio.sleep(2 ** attempt)  # Exponential backoff
			continue
```

---

## Rate Limiting

### Configuration

```python
RATE_LIMIT_REQUESTS = 100              # requests
RATE_LIMIT_WINDOW = 60                 # seconds
```

### Headers

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1653126660
```

### When Limited

You'll receive:

```
HTTP/1.1 429 Too Many Requests
X-RateLimit-Retry-After: 30

{
  "detail": "Rate limit exceeded",
  "retry_after_seconds": 30
}
```

### Best Practices

1. Respect `X-RateLimit-Remaining` header
2. Implement exponential backoff on 429
3. Cache responses when possible
4. Batch requests if applicable

---

## Data Models

### Request Models

#### ChatRequest
```python
class ChatRequest(BaseModel):
	message: str                        # User's question
	mode: str = "research"              # research | marathon
```

#### ResearchRequest
```python
class ResearchRequest(BaseModel):
	query: str                          # What to research
	depth: str = "deep"                 # chat | standard | deep | marathon
	target: str | None = None           # Specific ticker (auto-extracted)
```

### Response Models

#### ChatResponse
```python
class ChatResponse(BaseModel):
	reply: str                          # Main response text
	agents_used: list[str]              # Which agents ran
	rich: dict[str, Any] | None = None  # Charts, tables, etc
	output_mode: str | None = None      # narrative | chart | table
	response_depth: str | None = None   # Actual depth used
```

#### ResearchResponse
```python
class ResearchResponse(BaseModel):
	session_id: str                     # UUID
	status: str                         # running | complete | failed
	created_at: datetime
	query: str
	depth: str
	events_url: str
	progress: float = 0.0               # 0-100%
```

#### SessionStatus
```python
class SessionStatus(BaseModel):
	session_id: str
	status: str                         # running | complete | failed
	progress: float                     # 0-100%
	current_phase: str
	phases_complete: list[str]
	total_time_seconds: float
	result: dict | None
```

### Rich Output Models

#### Chart
```python
class Chart(BaseModel):
	type: str                           # candlestick | line | bar | gauge
	title: str
	data: list[dict]
	color: str = "blue"
```

#### Table
```python
class Table(BaseModel):
	headers: list[str]
	rows: list[list[str]]
	title: str | None = None
```

#### RichOutput
```python
class RichOutput(BaseModel):
	text: str | None = None
	chart: Chart | None = None
	table: Table | None = None
	list_items: list[str] | None = None
	citations: list[Citation] | None = None
```

#### Citation
```python
class Citation(BaseModel):
	text: str                           # What was cited
	source: str                         # Where it came from
	url: str | None = None              # Link to source
	confidence: float                   # 0.0-1.0
```

---

## Code Examples

### Example 1: Quick Chat

**Python:**
```python
import httpx
import json

async def quick_chat(query: str):
	async with httpx.AsyncClient() as client:
		response = await client.post(
			"http://localhost:8000/api/chat",
			json={"message": query, "mode": "research"}
		)
		result = response.json()
		print(f"Reply: {result['reply']}")
		print(f"Agents: {', '.join(result['agents_used'])}")
		if result.get('rich'):
			print(f"Rich output: {json.dumps(result['rich'], indent=2)}")

# Run
import asyncio
asyncio.run(quick_chat("What is TCS's PE ratio?"))
```

### Example 2: Stream Response

**JavaScript:**
```javascript
async function streamChat(query) {
  const response = await fetch('/api/stream', {
	method: 'POST',
	headers: { 'Content-Type': 'application/json' },
	body: JSON.stringify({ message: query })
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  while (true) {
	const { done, value } = await reader.read();
	if (done) break;

	const text = decoder.decode(value);
	console.log(text);
  }
}

streamChat("Compare TCS and Infosys");
```

### Example 3: Deep Research with Real-Time Updates

**Python:**
```python
import httpx
import json
import asyncio

async def deep_research(query: str):
	async with httpx.AsyncClient() as client:
		# Start research
		start_response = await client.post(
			"http://localhost:8000/api/research",
			json={"query": query, "depth": "deep"}
		)
		session = start_response.json()
		session_id = session['session_id']

		print(f"Research started: {session_id}")
		print("Subscribing to events...\n")

		# Subscribe to events
		async with client.stream(
			"GET",
			f"http://localhost:8000/api/session/{session_id}/events"
		) as event_response:
			async for line in event_response.aiter_lines():
				if line.startswith('data: '):
					event = json.loads(line[6:])

					if 'phase' in event:
						print(f"Phase: {event['phase']} ({event.get('progress', 0)}%)")
					elif 'research_complete' in str(event):
						print(f"\n✅ Research Complete!")
						print(f"Memo: {event.get('memo_url')}")
						print(f"Quality: {event.get('quality_score')}/100")
						print(f"Time: {event.get('total_time_seconds')}s")
						break

asyncio.run(deep_research("Analyze TCS fundamentals"))
```

---

## WebSocket / SSE

### Server-Sent Events (SSE) Format

All streaming uses **Server-Sent Events** (not WebSocket):

```
event: event_name
data: {"key": "value"}

event: another_event
data: {"key": "value"}
```

### Connecting to SSE Stream

**JavaScript:**
```javascript
const source = new EventSource('/api/session/{id}/events');

source.addEventListener('phase_start', e => {
  console.log(JSON.parse(e.data));
});

source.addEventListener('error', e => {
  console.error('Connection error');
  source.close();
});
```

**Python:**
```python
import httpx
import json

async with httpx.AsyncClient() as client:
	async with client.stream(
		'GET',
		'/api/session/{id}/events'
	) as response:
		async for line in response.aiter_lines():
			if line.startswith('data: '):
				print(json.loads(line[6:]))
```

### Event Structure

```
event: {event_type}
id: {optional_sequence_id}
retry: {milliseconds_to_wait_before_retry}
data: {JSON_data}

```

---

## OpenAPI/Swagger

Auto-generated API docs available at:

```
http://localhost:8000/docs                 # Swagger UI
http://localhost:8000/redoc                # ReDoc
http://localhost:8000/openapi.json         # OpenAPI schema
```

---

## Integration Checklist

- [ ] Test `/api/chat` endpoint
- [ ] Test `/api/stream` endpoint
- [ ] Implement SSE event handler
- [ ] Add error handling (429, 503)
- [ ] Implement retry logic
- [ ] Test rate limiting
- [ ] Cache responses where applicable
- [ ] Monitor latency
- [ ] Add logging
- [ ] Document integrations

---

## Troubleshooting

### "Connection refused"
- Backend not running? `python -m uvicorn Backend.api:app --reload`
- Wrong port? Check `localhost:8000` vs production URL

### "OpenAI authentication failed"
- Set `OPENAI_API_KEY` in `.env`
- Key expired? Check https://platform.openai.com

### "Rate limit exceeded"
- Wait `retry_after_seconds`
- Implement backoff strategy
- Cache results where possible

### "MCP service unavailable"
- Check if MCP services are running on ports 8001-8005
- Backend will fallback to web search

### "Timeout"
- Query taking too long?
- Check `GRAPH_RUN_TIMEOUT_SECONDS` (default 240s)
- Response may still succeed, give it time

---

**Last Updated:** May 21, 2026  
**API Version:** 2.0.0  
**Repository:** https://github.com/K-u-s-h-gupta/Prospektlab_intelligence

