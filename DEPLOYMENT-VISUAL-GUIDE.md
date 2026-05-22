# 🎯 Production Deployment - Visual Guide

## Architecture After Deployment

```
┌─────────────────────────────────────────────────────────────────┐
│                     AWS Production Environment                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐                    ┌──────────────┐          │
│  │   Amplify    │                    │  API Gateway │          │
│  │   Frontend   │◄────HTTPS─────────►│   or ALB     │          │
│  │              │ (your-domain.com)  │              │          │
│  └──────────────┘                    └──────┬───────┘          │
│                                             │                  │
│                                             ▼                  │
│                                    ┌──────────────┐            │
│                                    │     ECS      │            │
│                                    │    Cluster   │            │
│                                    │              │            │
│                                    │ ┌──────────┐ │            │
│                                    │ │ Backend  │ │            │
│                                    │ │:8080     │ │            │
│                                    │ └──────────┘ │            │
│                                    │              │            │
│                                    └──────┬───────┘            │
│                                           │                   │
│                      ┌────────────────────┼────────────────┐  │
│                      │                    │                │  │
│                      ▼                    ▼                ▼  │
│            ┌─────────────────┐  ┌─────────────────┐┌──────┐ │
│            │  MCP Services   │  │ MCP Services    ││ ... │ │
│            │  NSE :8001      │  │ Fundamentals    ││     │ │
│            │  (:8001-8005)   │  │ :8002           ││     │ │
│            │                 │  │ (:8002-8005)    ││     │ │
│            └─────────────────┘  └─────────────────┘└──────┘ │
│                      │                    │                │  │
│                      ▼                    ▼                ▼  │
│            ┌─────────────────┐  ┌─────────────────┐┌──────┐ │
│            │ External APIs   │  │ External APIs   ││...   │ │
│            │ NSE India       │  │ Yahoo Finance   ││      │ │
│            │ Screener.in     │  │ Tavily Search   ││      │ │
│            │ Moneycontrol    │  │ Qdrant Vector DB││      │ │
│            └─────────────────┘  └─────────────────┘└──────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Deployment Timeline

```
START
  │
  ▼
┌─────────────────────────────┐
│ 1. Configure Environment    │  ⏱ 5-10 min
│    Variables                │
└────────┬────────────────────┘
		 │
		 ▼
	┌─────────┐
	│ Choose  │
	│ Method  │
	└────┬────┘
		 │
	┌────┴─────────┬──────────────┬──────────────┐
	│              │              │              │
	▼              ▼              ▼              ▼
┌────────┐   ┌─────────┐   ┌──────────┐   ┌─────────┐
│GitHub  │   │ Bash    │   │ AWS CLI  │   │CodeBuild│
│Actions │   │Script   │   │ Commands │   │         │
│ ⏱5-10m │   │⏱5-10m  │   │⏱10-15m  │   │⏱5-10m  │
└────┬───┘   └────┬────┘   └────┬─────┘   └────┬────┘
	 │           │             │             │
	 └───────┬───┴─────────────┴─────────────┘
			 │
			 ▼
	┌─────────────────────┐
	│ 2. Build Docker     │  ⏱ ~2 min
	│    Image & Push     │
	│    to ECR           │
	└────────┬────────────┘
			 │
			 ▼
	┌─────────────────────┐
	│ 3. Update ECS Task  │  ⏱ ~1 min
	│    Definition       │
	└────────┬────────────┘
			 │
			 ▼
	┌─────────────────────┐
	│ 4. Deploy to ECS    │  ⏱ ~2-5 min
	│    (Rolling Update) │
	└────────┬────────────┘
			 │
			 ▼
	┌─────────────────────┐
	│ 5. Wait for Stable  │  ⏱ ~1-2 min
	│    (No more updates)│
	└────────┬────────────┘
			 │
			 ▼
	┌─────────────────────┐
	│ 6. Run Health       │  ⏱ ~1 min
	│    Checks           │
	└────────┬────────────┘
			 │
			 ▼
	┌─────────────────────┐
	│ 7. Verify MCP       │  ⏱ ~1 min
	│    Services         │
	└────────┬────────────┘
			 │
			 ▼
		   SUCCESS ✅
	  Total: 5-15 minutes
```

---

## Deployment Decision Tree

```
						🚀 Ready to Deploy?
							   │
				┌──────────────┴──────────────┐
				│                             │
		   YES  ▼                         NO  ▼
		 ┌──────────┐                  ┌──────────┐
		 │ Proceed  │                  │ Review   │
		 └────┬─────┘                  │ Checklist│
			  │                        └──────────┘
			  │
	  ┌───────▼────────┐
	  │ Have GitHub    │
	  │ Actions setup? │
	  └───┬──────────┬─┘
		  │YES   NO  │
		  │          │
	  ┌───▼──┐  ┌────▼───┐
	  │ Push │  │ Choose │
	  │to    │  │another │
	  │prod  │  │ method │
	  └──┬───┘  └─┬──┬───┘
		 │        │  │
		 │   ┌────┘  │
		 │   │   ┌───┘
		 │   ▼   ▼
		 │  Bash AWS CLI
		 │  Script Commands
		 │   │      │
		 └───┼──────┘
			 │
			 ▼
		DEPLOY! 🚀
```

---

## File Organization

```
ProspektLab/
├── 📝 Documentation
│   ├── INDEX.md                               ← START HERE
│   ├── QUICK_START_DEPLOYMENT.md             ← 5-min overview
│   ├── DEPLOYMENT-QUICK-REFERENCE.md         ← Cheat sheet
│   ├── PRODUCTION_DEPLOYMENT_GUIDE.md        ← Full config
│   ├── PRODUCTION_VERIFICATION_CHECKLIST.md  ← Testing
│   ├── PRE-DEPLOYMENT-CHECKLIST.md           ← Pre-flight
│   ├── DEPLOYMENT-SUMMARY.md                 ← Changes overview
│   └── CHANGE-SUMMARY.md                     ← Technical changes
│
├── 🚀 Deployment Scripts
│   ├── deploy-production.sh                  ← Bash automation
│   ├── AWS-DEPLOYMENT-COMMANDS.sh            ← CLI reference
│   ├── buildspec-prod.yml                    ← CodeBuild config
│   ├── amplify-buildspec.yml                 ← Amplify config
│   └── .github/
│       └── workflows/
│           └── deploy-production.yml         ← GitHub Actions
│
├── 💻 Modified Code
│   ├── Backend/api.py                        ✏️
│   ├── finagent/tools/mcp_config.py         ✏️
│   ├── finagent/api.py                       ✏️
│   └── finagent/gateway/widget.html          ✏️
│
└── 📦 Other
	├── Dockerfile                             (unchanged)
	├── buildspec.yml                          (original)
	└── requirements-finagent.txt              (unchanged)
```

---

## Command Quick Links

### Start Deployment (Choose One)

**GitHub Actions (Auto)**
```bash
git push origin production
# Watch at: https://github.com/YOUR_REPO/actions
```

**Bash Script**
```bash
chmod +x deploy-production.sh
./deploy-production.sh
```

**AWS CLI**
```bash
source AWS-DEPLOYMENT-COMMANDS.sh
# Follow step-by-step instructions
```

### Verification

```bash
# Health Check
curl https://api.prospektlab.com/health

# MCP Status
curl https://api.prospektlab.com/api/health/mcp

# Test Chat
curl -X POST https://api.prospektlab.com/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"test","mode":"research"}'
```

### Monitoring

```bash
# View Logs
aws logs tail /ecs/prospektlab-backend --follow

# Check Status
aws ecs describe-services \
  --cluster prospektlab-prod \
  --services prospektlab-backend

# Rollback
aws ecs update-service --cluster prospektlab-prod \
  --service prospektlab-backend --force-new-deployment
```

---

## Environment Variables Map

```
┌─────────────────────────────────────────────────────────┐
│              Environment Variables Needed               │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ECS Task Definition:                                   │
│  ┌─────────────────────────────────────────────────┐   │
│  │ CORS_ORIGINS = amplify-domain.amplifyapp.com    │   │
│  │ MCP_NSE_INDIA_URL = http://mcp-nse:8001/mcp    │   │
│  │ MCP_FUNDAMENTALS_URL = http://mcp-fund:8002/mcp│   │
│  │ MCP_RESEARCH_URL = http://mcp-research:8003/mcp│   │
│  │ MCP_DOCS_URL = http://mcp-docs:8004/mcp         │   │
│  │ MCP_VALUATION_URL = http://mcp-val:8005/mcp     │   │
│  │ OPENAI_API_KEY = sk-xxxx...                     │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  Amplify Environment:                                   │
│  ┌─────────────────────────────────────────────────┐   │
│  │ BACKEND_API_URL = https://api.prospektlab.com   │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  GitHub Secrets (if using Actions):                     │
│  ┌─────────────────────────────────────────────────┐   │
│  │ AWS_ROLE_TO_ASSUME = arn:aws:iam::...          │   │
│  │ BACKEND_URL = https://api.prospektlab.com       │   │
│  │ AMPLIFY_DOMAIN = https://app.prospektlab.com    │   │
│  │ OPENAI_API_KEY = sk-xxxx...                     │   │
│  │ [MCP URLs from ECS Task Definition]             │   │
│  │ AMPLIFY_APP_ID = xxxxx (optional)               │   │
│  │ SLACK_WEBHOOK_URL = https://... (optional)      │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## Success Indicators

```
After Deployment:

✅ Backend responds to health check (200 OK)
✅ MCP services all show "ok": true
✅ Frontend loads without errors
✅ Can submit queries in chat
✅ Agent processes requests
✅ No 5xx errors in logs (after 1 hour)
✅ Response times are normal
✅ No CORS errors in browser console

If all ✅ = SUCCESS! 🎉
```

---

## Troubleshooting Flow

```
Issue: Agent not working

│
├─ Check 1: Is backend running?
│  └─ curl https://api.prospektlab.com/health
│     └─ If 200 ✅ → Go to Check 2
│     └─ If error ❌ → Check logs, restart ECS task
│
├─ Check 2: Are MCP services accessible?
│  └─ curl https://api.prospektlab.com/api/health/mcp
│     └─ If all_ok: true ✅ → Go to Check 3
│     └─ If all_ok: false ❌ → Fix MCP URLs, restart services
│
├─ Check 3: Can frontend connect?
│  └─ Open browser DevTools
│  └─ console.log(window.__BACKEND_URL)
│     └─ If shows backend URL ✅ → Go to Check 4
│     └─ If empty/wrong ❌ → Update Amplify BACKEND_API_URL
│
├─ Check 4: Test chat endpoint
│  └─ curl -X POST https://api.prospektlab.com/api/chat ...
│     └─ If valid response ✅ → SUCCESS!
│     └─ If error ❌ → Check logs for agent error
│
└─ Still broken?
   └─ ROLLBACK: aws ecs update-service --force-new-deployment
```

---

## What's Actually Deployed

```
ECS Container Registry (ECR)
└─ prospektlab-backend:latest
   └─ Python 3.11 image
	  ├─ FastAPI app (port 8080)
	  ├─ Backend service (api.py)
	  ├─ MCP client integration
	  └─ Agent orchestration (LangGraph)

ECS Cluster & Service
└─ prospektlab-prod cluster
   └─ prospektlab-backend service
	  ├─ Task Definition (CPU/Memory)
	  ├─ Environment Variables
	  ├─ CloudWatch Logs
	  ├─ Security Groups
	  └─ Load Balancer Integration

Amplify
└─ Frontend app
   ├─ Widget HTML/JS
   ├─ Backend URL Configuration
   ├─ Custom Domain
   └─ SSL Certificate

Networking
├─ API Gateway / ALB
├─ Security Groups
├─ VPC/Subnets
└─ DNS Records
```

---

## Performance Expectations

```
After Deployment:

Chat Response Time:
├─ Simple query: 5-10 seconds
├─ Complex query: 15-30 seconds
├─ With document analysis: 30-60 seconds
└─ Edge case: up to 240 seconds (max timeout)

MCP Service Latency:
├─ NSE (Market Data): 50-200ms
├─ Fundamentals: 100-500ms
├─ Research (Search): 200-1000ms
├─ Documents: 500-2000ms
└─ Valuation: 100-500ms

System Health:
├─ CPU Usage: 20-40% average
├─ Memory Usage: 30-50% of allocated
├─ Error Rate: <0.1%
└─ Availability: 99.5%+
```

---

## Next Steps Summary

```
1️⃣  READ  → QUICK_START_DEPLOYMENT.md (10 min)
2️⃣  PLAN  → PRE-DEPLOYMENT-CHECKLIST.md (30 min)
3️⃣  SETUP → Set environment variables (10 min)
4️⃣  TEST  → Local Docker test (10 min)
5️⃣  DEPLOY→ Choose & run deployment (5-10 min)
6️⃣  VERIFY→ Run health checks (10 min)
7️⃣  MONITOR→ Watch logs (ongoing)
```

---

## 🎉 You're Ready!

All documentation complete.
All code changes validated.
All deployment tools prepared.

**Pick a deployment method and go! 🚀**

---

*Last Updated: 2024*  
*Status: Production Ready ✅*
