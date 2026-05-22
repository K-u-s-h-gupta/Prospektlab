# 🚀 Deployment Quick Reference

## TL;DR - Deploy in 5 Minutes

```bash
# 1. Set variables
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export BACKEND_URL=https://api.prospektlab.com
export AMPLIFY_DOMAIN=https://app.prospektlab.com

# 2. Run script
chmod +x deploy-production.sh
./deploy-production.sh

# 3. Verify
curl https://api.prospektlab.com/health  # Should return 200
```

---

## Environment Variables Checklist

```bash
# ECS Task Definition
✅ CORS_ORIGINS = your-amplify-domain.amplifyapp.com
✅ MCP_NSE_INDIA_URL = http://mcp-nse-service:8001/mcp
✅ MCP_FUNDAMENTALS_URL = http://mcp-fundamentals-service:8002/mcp
✅ MCP_RESEARCH_URL = http://mcp-research-service:8003/mcp
✅ MCP_DOCS_URL = http://mcp-docs-service:8004/mcp
✅ MCP_VALUATION_URL = http://mcp-valuation-service:8005/mcp
✅ OPENAI_API_KEY = your-key

# Amplify
✅ BACKEND_API_URL = https://api.prospektlab.com
```

---

## Deployment Methods

| Method | Time | Effort | Best For |
|--------|------|--------|----------|
| **GitHub Actions** | 5-10m | Low | Automated CI/CD |
| **Bash Script** | 5-10m | Medium | Quick manual deploy |
| **AWS CLI** | 10-15m | High | Fine control |
| **CodeBuild** | 5-10m | Low | AWS-native CI/CD |

---

## Health Check URLs

```bash
# Backend health
curl https://api.prospektlab.com/health

# MCP services
curl https://api.prospektlab.com/api/health/mcp

# Test chat
curl -X POST https://api.prospektlab.com/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"test","mode":"research"}'
```

---

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| 502 Gateway | `curl health` | Restart ECS task |
| CORS error | Browser console | Update CORS_ORIGINS |
| MCP down | `/api/health/mcp` | Check service URLs |
| Timeout | CloudWatch logs | Increase timeout or scale up |
| Frontend blank | `window.__BACKEND_URL` | Update Amplify BACKEND_API_URL |

---

## Useful Commands

```bash
# View logs
aws logs tail /ecs/prospektlab-backend --follow

# Check deployment
aws ecs describe-services --cluster prospektlab-prod \
  --services prospektlab-backend

# Rollback
aws ecs update-service --cluster prospektlab-prod \
  --service prospektlab-backend --force-new-deployment

# Scale
aws ecs update-service --cluster prospektlab-prod \
  --service prospektlab-backend --desired-count 2
```

---

## Key Files

| File | Purpose |
|------|---------|
| `QUICK_START_DEPLOYMENT.md` | **START HERE** |
| `PRODUCTION_DEPLOYMENT_GUIDE.md` | Full config |
| `deploy-production.sh` | Auto script |
| `PRE-DEPLOYMENT-CHECKLIST.md` | Pre-flight |
| `AWS-DEPLOYMENT-COMMANDS.sh` | CLI reference |

---

## Emergency Rollback

```bash
# If something breaks
aws ecs update-service --cluster prospektlab-prod \
  --service prospektlab-backend --force-new-deployment

# Check status
aws ecs describe-services --cluster prospektlab-prod \
  --services prospektlab-backend --query 'services[0].{running:runningCount,desired:desiredCount}'
```

---

## GitHub Actions Setup

1. Go to Repo → Settings → Secrets
2. Add secrets (see `QUICK_START_DEPLOYMENT.md`)
3. Push to production branch
4. Watch Actions tab for progress
5. Get Slack notification (if configured)

---

## What Gets Deployed

```
✅ Backend (ECS) - Port 8080
✅ MCP Servers (ECS) - Ports 8001-8005
✅ Frontend (Amplify) - Custom domain
✅ OpenAI integration
✅ Environment variables
```

---

## Post-Deployment (10 mins)

- [ ] `curl health` → 200 ✅
- [ ] `curl /api/health/mcp` → all_ok: true ✅
- [ ] Frontend loads ✅
- [ ] Can submit query ✅
- [ ] Agent responds ✅
- [ ] No errors in logs ✅

---

## Important ⚠️

1. **CORS_ORIGINS must match Amplify domain**
2. **MCP URLs must be accessible from ECS**
3. **OpenAI key must be valid**
4. **Deploy backend before/with frontend**
5. **Monitor logs after deployment**

---

## Success = ✅

- Backend responds to health check
- MCP services connected
- Frontend loads without errors
- Chat endpoint works
- Agent executes queries

🎉 **You're done!**

---

## Need Help?

1. Check logs: `aws logs tail /ecs/prospektlab-backend`
2. Verify health: `curl https://api.prospektlab.com/health`
3. Read docs: `PRODUCTION_VERIFICATION_CHECKLIST.md`
4. Rollback: See Emergency Rollback above

---

**Last Updated:** 2024
**Status:** Production Ready ✅
