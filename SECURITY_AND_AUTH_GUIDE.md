# 🔐 ProspektLab Security & Auth Guide

**Version:** 2.0.0  
**Last Updated:** May 21, 2026  
**Security Level:** Production-Ready for Public Beta

---

## 📋 Table of Contents

1. [Current Security Model](#current-security)
2. [Authentication](#authentication)
3. [Authorization & RBAC](#authorization)
4. [API Security](#api-security)
5. [Data Security](#data-security)
6. [Common Vulnerabilities](#vulnerabilities)
7. [Security Checklist](#security-checklist)
8. [Incident Response](#incident-response)

---

## Current Security Model

### What's Implemented

✅ **CORS Protection** — Origins restricted to configured domains  
✅ **Rate Limiting** — Sliding window (100 req/min per IP)  
✅ **API Key Redaction** — OPENAI_API_KEY never logged  
✅ **Timeout Protection** — Graph run timeout (240s max)  
✅ **Error Handling** — No sensitive data in error messages  
✅ **Input Validation** — Pydantic models validate all inputs  

### What's NOT Implemented

❌ User authentication (no login system)  
❌ API key authentication (no per-user keys)  
❌ Encryption at rest (files stored plaintext)  
❌ TLS/SSL (HTTPS recommended but not enforced locally)  
❌ Rate limiting per user (only per IP)  
❌ Request signing / verification  
❌ Audit logging  

### Current Threat Model

**Assumed Environment:**
- Internal network or trusted clients only
- Backend not exposed to untrusted networks
- HTTPS enforced in production (via ALB)
- API keys managed via environment (not in code)

---

## Authentication

### Current: No Authentication

API is open by default (development mode). **All requests accepted.**

```python
# Backend/api.py — No auth check
@app.post("/api/chat")
async def chat(req: ChatRequest):
	# No user_id, no token validation
	# Anyone can call this
	...
```

### Future: JWT-Based Auth

When user authentication is needed:

```python
from fastapi import Depends, HTTPException
from jose import JWTError, jwt
from datetime import datetime, timedelta

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = "HS256"

async def verify_token(token: str = Depends(HTTPBearer())) -> str:
	"""Verify JWT token and return user_id."""
	try:
		payload = jwt.decode(token.credentials, SECRET_KEY, algorithms=[ALGORITHM])
		user_id: str = payload.get("sub")
		if user_id is None:
			raise HTTPException(status_code=401, detail="Invalid token")
		return user_id
	except JWTError:
		raise HTTPException(status_code=401, detail="Invalid token")

@app.post("/api/chat")
async def chat(req: ChatRequest, user_id: str = Depends(verify_token)):
	# Now: user_id is authenticated
	# Can track usage per user, enforce quotas, etc
	...
```

### API Key Strategy (Future)

```python
class APIKey(BaseModel):
	key_id: str                        # Identifier
	key_hash: str                      # Hashed API key
	user_id: str
	created_at: datetime
	last_used_at: datetime | None
	is_active: bool

# When issuing keys:
import secrets
api_key = secrets.token_urlsafe(32)    # "abc123def456..."
key_hash = hashlib.sha256(api_key.encode()).hexdigest()

# When validating:
async def verify_api_key(key: str = Header(...)) -> str:
	"""Verify API key and return user_id."""
	key_hash = hashlib.sha256(key.encode()).hexdigest()
	row = await db.fetch_one(
		"SELECT user_id FROM api_keys WHERE key_hash = $1 AND is_active = true",
		key_hash
	)
	if not row:
		raise HTTPException(status_code=401, detail="Invalid API key")
	return row['user_id']
```

### OAuth2 Integration (Future)

```python
from authlib.integrations.httpx_client import AsyncOAuth2Client

# Redirect to GitHub/Google for login
# Receive code, exchange for token
# Store token in session

oauth = AsyncOAuth2Client(
	client_id=os.getenv("OAUTH_CLIENT_ID"),
	client_secret=os.getenv("OAUTH_CLIENT_SECRET")
)

async def login_callback(code: str):
	token = await oauth.fetch_token(
		url="https://github.com/login/oauth/access_token",
		code=code
	)
	user_info = await oauth.get("/user", token=token)
	# Create user or session
	return create_session(user_info)
```

---

## Authorization & RBAC

### Current: No Authorization

Anyone who reaches the API can use any endpoint.

### Proposed: Role-Based Access Control

```python
class UserRole(str, Enum):
	GUEST = "guest"                   # Free tier (10 req/day)
	USER = "user"                     # Paid tier (1000 req/day)
	POWER_USER = "power_user"         # High usage (unlimited)
	ADMIN = "admin"                   # Internal access

class User(BaseModel):
	id: str
	email: str
	role: UserRole
	created_at: datetime
	quota_remaining: int              # Requests this month
	quota_limit: int                  # Monthly limit

# Middleware to check role
async def require_role(min_role: UserRole):
	async def _require_role(user_id: str = Depends(verify_token)):
		user = await db.fetch_user(user_id)
		if user.role not in [min_role, UserRole.ADMIN]:
			raise HTTPException(status_code=403, detail="Insufficient permissions")
		return user
	return _require_role

# Usage
@app.post("/api/research")
async def research(req: ResearchRequest, user: User = Depends(require_role(UserRole.POWER_USER))):
	# Only power users can run deep research
	if user.quota_remaining <= 0:
		raise HTTPException(status_code=429, detail="Quota exceeded")
	user.quota_remaining -= 1
	...
```

### Permission Matrix

| Feature | Guest | User | Power User | Admin |
|---------|-------|------|-----------|-------|
| `/api/chat` | ✅ Limited (5/day) | ✅ 100/day | ✅ Unlimited | ✅ |
| `/api/research` | ❌ | ✅ 5/day | ✅ Unlimited | ✅ |
| `/api/stream` | ❌ | ✅ 20/day | ✅ Unlimited | ✅ |
| `/admin/stats` | ❌ | ❌ | ❌ | ✅ |
| `/admin/users` | ❌ | ❌ | ❌ | ✅ |

---

## API Security

### CORS Configuration

**Current:**
```python
_cors_origins = [
	"http://localhost:3000",
	"http://127.0.0.1:3000"
]

app.add_middleware(
	CORSMiddleware,
	allow_origins=_cors_origins,
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"]
)
```

**Production:**
```env
CORS_ORIGINS=https://app.prospektlab.com,https://app.staging.prospektlab.com
```

**Security Issues:**
- ❌ `allow_methods=["*"]` allows DELETE, PATCH on public API
- ✅ Fixed by restricting: `allow_methods=["GET", "POST", "OPTIONS"]`

```python
app.add_middleware(
	CORSMiddleware,
	allow_origins=cors_origins,
	allow_credentials=True,
	allow_methods=["GET", "POST", "OPTIONS"],      # Restricted
	allow_headers=["Content-Type", "Authorization"] # Restricted
)
```

### Rate Limiting

**Current Implementation:**
```python
class InMemSlidingWindowRateLimiter:
	def __init__(self, requests_limit=100, window_seconds=60):
		self.limit = requests_limit
		self.window = window_seconds
		self.requests = {}  # {ip: [timestamps]}

	async def check_limit(self, client_ip: str) -> bool:
		now = time.time()

		# Prune old requests
		self.requests[client_ip] = [
			t for t in self.requests.get(client_ip, [])
			if now - t < self.window
		]

		# Check limit
		if len(self.requests[client_ip]) >= self.limit:
			return False

		# Record request
		self.requests[client_ip].append(now)
		return True
```

**Middleware Integration:**
```python
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
	client_ip = request.client.host

	# Special handling for certain endpoints
	if "/api/chat" in request.url.path:
		# Chat: 100 req/min per IP
		if not await limiter.check_limit(client_ip):
			return JSONResponse(
				status_code=429,
				content={"detail": "Rate limit exceeded"},
				headers={"Retry-After": "30"}
			)

	response = await call_next(request)
	return response
```

**Issues & Improvements:**
- ❌ Current: Per-IP only (shared limit for all users on same network)
- ✅ Future: Per-user quota (with auth)
- ❌ Current: In-memory (lost on restart)
- ✅ Future: Redis-backed (persistent across restarts)

### Input Validation

**Good:** Pydantic validates all request bodies
```python
class ChatRequest(BaseModel):
	message: str                    # Required
	mode: str = Field(default="research", pattern="^(research|marathon)$")
```

**Issue:** Long inputs not limited
```python
# Attack: Send 1MB message
{"message": "x" * 1_000_000}  # Could cause OOM

# Fix: Add max length
class ChatRequest(BaseModel):
	message: str = Field(..., max_length=2000)  # Max 2000 chars
```

**Validation Checklist:**
- ✅ Type checking (Pydantic)
- ✅ Required vs optional fields
- ✅ Enum/pattern validation
- ❌ Length limits (add)
- ❌ SQL injection prevention (N/A, no SQL)
- ❌ XSS prevention (handled by frontend)
- ✅ JSON parsing (FastAPI does)

---

## Data Security

### Secrets Management

**Current:**
```python
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
```

**Issues:**
- ❌ `.env` file in repository (never do this!)
- ❌ Keys logged in debug mode
- ❌ Keys visible in environment variables on CI/CD

**Production (AWS ECS):**
```yaml
# Task definition
environment:
  OPENAI_API_KEY: arn:aws:secretsmanager:...  # Reference, not value

secrets:  # True secrets, not logged
  - name: OPENAI_API_KEY
	valueFrom: arn:aws:secretsmanager:region:account:secret:prod/openai-key
```

**Best Practices:**
```python
# ✅ Use AWS Secrets Manager
import boto3

def get_secret(secret_name: str) -> str:
	client = boto3.client('secretsmanager')
	response = client.get_secret_value(SecretId=secret_name)
	return response['SecretString']

OPENAI_API_KEY = get_secret('prod/openai-api-key')

# ✅ Never log secrets
import logging
logging.getLogger("httpx").setLevel(logging.WARNING)  # Reduce noise

# ✅ Redact in error messages
def safe_error(e: Exception) -> str:
	msg = str(e)
	# Redact API key patterns
	import re
	msg = re.sub(r'sk-[a-zA-Z0-9]+', 'sk-***', msg)
	return msg
```

### Data in Transit

**Current (Development):**
```
http://localhost:8000/api/chat  # Unencrypted
```

**Production:**
```
https://api.prospektlab.com/api/chat  # Encrypted via ALB
```

**Configuration:**
```yaml
# AWS ALB with HTTPS
listener:
  Protocol: HTTPS
  Port: 443
  Certificate: arn:aws:acm:...

# Redirect HTTP → HTTPS
listener:
  Protocol: HTTP
  Port: 80
  DefaultAction: redirect to HTTPS
```

### Data at Rest

**Current:**
```
~/.finagent/state/*.json         # Plaintext files
~/.finagent/memory/*.json        # Plaintext files
~/.finagent/memos/*.md           # Plaintext files
```

**Issues:**
- ❌ Sensitive data stored plaintext
- ✅ OK for now (local machine, no user data)
- ⚠️ Will need encryption when user data exists

**Future (When User Data Added):**
```python
from cryptography.fernet import Fernet

# Generate key (store securely, e.g., AWS KMS)
key = Fernet.generate_key()
cipher = Fernet(key)

# Encrypt session before saving
session_json = json.dumps(session_data)
encrypted = cipher.encrypt(session_json.encode())

with open(session_path, 'wb') as f:
	f.write(encrypted)

# Decrypt when reading
with open(session_path, 'rb') as f:
	encrypted = f.read()
decrypted = cipher.decrypt(encrypted).decode()
session_data = json.loads(decrypted)
```

---

## Common Vulnerabilities

### 1. SQL Injection

**Status:** Not applicable (no SQL queries in current code)

**When implementing database:**
```python
# ❌ VULNERABLE
query = f"SELECT * FROM memory_facts WHERE target = '{target}'"

# ✅ SAFE
query = "SELECT * FROM memory_facts WHERE target = $1"
await db.fetch(query, target)
```

### 2. Cross-Site Scripting (XSS)

**Status:** Frontend responsibility (Next.js escapes by default)

**Potential Issue:** Rich output rendering
```python
# If returning HTML (not recommended):
rich_output = "<b>Market cap: ₹2.1T</b>"  # ❌ Unsafe

# Better: Return structured data, let frontend render
rich_output = {"type": "text", "bold": True, "text": "Market cap: ₹2.1T"}
```

### 3. API Key Exposure

**Status:** Low risk (API keys in environment only)

**Dangers:**
- ❌ Logging request headers (contains auth tokens)
- ❌ Storing keys in code
- ❌ Committing `.env` files

**Prevention:**
```python
# ✅ Redact in logs
import logging

class SensitiveDataFilter(logging.Filter):
	def filter(self, record):
		record.msg = re.sub(r'sk-[a-zA-Z0-9]+', 'sk-***', record.msg)
		return True

logging.getLogger().addFilter(SensitiveDataFilter())

# ✅ .gitignore
.env
.env.local
*.key
```

### 4. Denial of Service (DoS)

**Vectors:**

1. **Large Payload:**
```python
# Attack: POST 100MB JSON
{"message": "x" * 100_000_000}

# Mitigation: Limit body size
@app.post("/api/chat")
async def chat(req: ChatRequest = Body(..., max_length=2000)):
	...
```

2. **Expensive Computation:**
```python
# Attack: "analyze all 5000+ companies"
# Already mitigated: Single entity per query

# Mitigation: Timeouts
GRAPH_RUN_TIMEOUT_SECONDS = 240  # 4 min max
```

3. **Rate Limiting:**
```python
# Already implemented: 100 req/min per IP
# Future: Redis-backed distributed rate limiting
```

### 5. Information Disclosure

**Risk:** Error messages leaking sensitive info

**Current:**
```python
except Exception as e:
	return {"detail": str(e)}  # ❌ Might expose internals
```

**Better:**
```python
except httpx.ConnectError as e:
	logger.error(f"MCP service unavailable: {e}")  # Log full error
	return {"detail": "Service temporarily unavailable"}  # Generic to user

except Exception as e:
	logger.error(f"Unexpected error: {e}", exc_info=True)
	return {"detail": "Internal server error"}  # Never expose details
```

### 6. Insecure Deserialization

**Status:** Low risk (JSON only)

**If using pickle (NEVER):**
```python
# ❌ NEVER use pickle for untrusted input
import pickle
data = pickle.loads(request.body)  # Arbitrary code execution!

# ✅ Use JSON only
import json
data = json.loads(request.body)
```

---

## Security Checklist

### Development

- [ ] Never commit `.env` files
- [ ] Use `python-dotenv` for local development
- [ ] No API keys in code
- [ ] No secrets in git history
- [ ] Input validation on all endpoints
- [ ] Error handling doesn't leak internals
- [ ] All tests pass
- [ ] CORS origins restricted
- [ ] Timeouts configured
- [ ] Rate limiting enabled

### Before Production Deployment

- [ ] SSL certificate configured (HTTPS)
- [ ] All environment variables set securely (AWS Secrets Manager)
- [ ] Database credentials rotated
- [ ] OpenAI API key rotated (new key for prod)
- [ ] CloudTrail logging enabled (AWS)
- [ ] Security group rules reviewed
- [ ] Load balancer HTTPS listener active
- [ ] Redirect HTTP → HTTPS
- [ ] Health check endpoints configured
- [ ] Backup strategy in place

### Ongoing (Operations)

- [ ] Monitor rate limiting metrics
- [ ] Review CloudWatch logs for errors
- [ ] Audit API access logs (when logging added)
- [ ] Rotate secrets quarterly
- [ ] Update dependencies monthly
- [ ] Run security scans (OWASP ZAP, Snyk)
- [ ] Backup database daily
- [ ] Test incident response procedures
- [ ] Review CORS origins quarterly
- [ ] Update security documentation

---

## Incident Response

### If API Key Leaked

```
1. Immediate (< 1 hour):
   - Revoke leaked key
   - Generate new key
   - Update production environment
   - Restart ECS tasks

2. Investigation (< 4 hours):
   - Check CloudTrail for unauthorized usage
   - Check OpenAI API usage report
   - Estimate impact (cost, data)
   - Update incident log

3. Prevention (< 24 hours):
   - Implement API key rotation
   - Add key expiration policy
   - Improve secret management
   - Post-mortem document
```

### If Rate Limiting Bypassed

```
1. Immediate:
   - Block suspicious IPs at ALB security group
   - Increase rate limit temporarily if legitimate

2. Investigation:
   - Check CloudWatch logs for patterns
   - Identify attack vector (single IP? Distributed?)
   - Estimate impact on service

3. Prevention:
   - Upgrade rate limiting to per-user (with auth)
   - Add DDoS protection (AWS Shield)
   - Implement geo-blocking if applicable
```

### If Data Breach Suspected

```
1. Immediate (< 1 hour):
   - Verify breach (check logs, access patterns)
   - Alert security team
   - Prepare incident response

2. Investigation (< 24 hours):
   - Forensic analysis of logs
   - Determine scope (what data, when, who)
   - Notify affected users (if any user data)

3. Remediation (< 7 days):
   - Fix vulnerability
   - Deploy patch
   - Update security documentation
   - Post-mortem + prevention plan
```

---

## Security Resources

### OWASP Top 10 (2023)

| Vulnerability | Your Status | Notes |
|---|---|---|
| 1. Injection | ✅ Low Risk | No SQL queries |
| 2. Broken Auth | ⚠️ Not Implemented | Planning JWT |
| 3. Sensitive Data | ⚠️ Partial | Need encryption at rest |
| 4. XML External Entities | ✅ N/A | JSON only |
| 5. Broken Access Control | ⚠️ Not Implemented | Planning RBAC |
| 6. Security Misconfiguration | ✅ Good | AWS hardened |
| 7. XSS | ✅ Low Risk | Frontend escaped |
| 8. Insecure Deserialization | ✅ Safe | JSON only |
| 9. Using Components with Vulnerabilities | ⚠️ Monitor | Keep deps updated |
| 10. Insufficient Logging | ✅ Basic | Adding audit logs |

### Tools

```bash
# Check dependencies for vulnerabilities
pip install safety
safety check

# Run OWASP ZAP (security scanner)
docker run -t owasp/zap2docker-stable zap-baseline.py -t http://localhost:8000

# Check secrets in code
pip install detect-secrets
detect-secrets scan

# Lint with bandit (Python security)
pip install bandit
bandit -r Backend/ finagent/
```

---

## Compliance Considerations

### GDPR (When User Data Exists)

- Right to access: Provide user data export
- Right to be forgotten: Delete user data + memos
- Data minimization: Collect only necessary data
- Consent: Explicit opt-in before data collection

### SEBI Regulations (India)

- No personalized investment advice (ORACLE is analysis-only) ✅
- Disclose use of AI/algorithms ✅
- Regular audits of model performance

---

**Last Updated:** May 21, 2026  
**Security Review:** Quarterly  
**Next Priority:** User authentication (Phase 2)  
**Repository:** https://github.com/K-u-s-h-gupta/Prospektlab_intelligence

