# 📚 ProspektLab Production Deployment - Master Index

## 🎯 Start Here

> **New to deployment?** Start with **`QUICK_START_DEPLOYMENT.md`** for a 5-minute overview.

---

## 📋 Documentation Map

### Quick References
- **`DEPLOYMENT-QUICK-REFERENCE.md`** - TL;DR cheat sheet (5 min read)
- **`QUICK_START_DEPLOYMENT.md`** - Getting started guide (10 min read)
- **`DEPLOYMENT-SUMMARY.md`** - What's been changed (10 min read)

### Detailed Guides  
- **`PRODUCTION_DEPLOYMENT_GUIDE.md`** - Complete configuration reference (30 min read)
- **`PRODUCTION_VERIFICATION_CHECKLIST.md`** - Testing & troubleshooting (20 min read)
- **`CHANGE-SUMMARY.md`** - Technical changes summary (15 min read)

### Pre-Deployment
- **`PRE-DEPLOYMENT-CHECKLIST.md`** - Pre-flight checklist (30 min to complete)

---

## 🚀 Deployment Tools

### Automated Scripts
| File | Method | Time | Effort | Best For |
|------|--------|------|--------|----------|
| `deploy-production.sh` | Bash | 5-10m | Medium | Quick manual deploy |
| `.github/workflows/deploy-production.yml` | GitHub Actions | 5-10m | Low | Automated CI/CD |
| `buildspec-prod.yml` | AWS CodeBuild | 5-10m | Low | Enterprise CI/CD |
| `AWS-DEPLOYMENT-COMMANDS.sh` | AWS CLI | 10-15m | High | Fine control |

### Configuration Files
- `amplify-buildspec.yml` - Amplify frontend build config

---

## 📁 Modified Files (4 Files)

```
✏️ Backend/api.py                    - CORS environment variable
✏️ finagent/tools/mcp_config.py      - Environment-driven MCP URLs  
✏️ finagent/api.py                   - Real agent loop integration
✏️ finagent/gateway/widget.html      - Backend URL override
```

**All changes are backward compatible and production-ready!**

---

## 🔧 Environment Variables

### ECS Task Definition (Required)
```
CORS_ORIGINS                    → https://your-amplify-domain.amplifyapp.com
MCP_NSE_INDIA_URL              → http://mcp-nse-service:8001/mcp
MCP_FUNDAMENTALS_URL           → http://mcp-fundamentals-service:8002/mcp
MCP_RESEARCH_URL               → http://mcp-research-service:8003/mcp
MCP_DOCS_URL                   → http://mcp-docs-service:8004/mcp
MCP_VALUATION_URL              → http://mcp-valuation-service:8005/mcp
OPENAI_API_KEY                 → sk-your-key-here
```

### Amplify (Required)
```
BACKEND_API_URL                → https://api.prospektlab.com
```

### GitHub Secrets (For CI/CD)
```
AWS_ROLE_TO_ASSUME             → arn:aws:iam::ACCOUNT:role/GitHubActionsRole
BACKEND_URL                    → https://api.prospektlab.com
AMPLIFY_DOMAIN                 → https://app.prospektlab.com
OPENAI_API_KEY                 → sk-your-key
MCP_NSE_URL                    → http://mcp-nse-service:8001/mcp
MCP_FUNDAMENTALS_URL           → http://mcp-fundamentals-service:8002/mcp
MCP_RESEARCH_URL               → http://mcp-research-service:8003/mcp
MCP_DOCS_URL                   → http://mcp-docs-service:8004/mcp
MCP_VALUATION_URL              → http://mcp-valuation-service:8005/mcp
AMPLIFY_APP_ID                 → your-app-id (optional)
SLACK_WEBHOOK_URL              → your-webhook (optional)
```

---

## 🎯 Deployment Workflows

### Workflow 1: GitHub Actions (Recommended)
```
1. Configure GitHub Secrets
2. Push to production branch
3. GitHub Actions runs automatically
4. Get Slack notification
5. Deployment complete!
```
**Time: 5-10 minutes**

### Workflow 2: Bash Script
```
1. Set environment variables
2. Run ./deploy-production.sh
3. Wait for completion
4. Verify health checks
```
**Time: 5-10 minutes**

### Workflow 3: AWS CLI
```
1. Build Docker image
2. Push to ECR
3. Update task definition
4. Update ECS service
5. Monitor progress
```
**Time: 10-15 minutes**

### Workflow 4: AWS CodeBuild
```
1. Create CodeBuild project
2. Configure buildspec-prod.yml
3. Trigger build
4. Deployment complete!
```
**Time: 5-10 minutes**

---

## ✅ Verification Steps

```bash
# 1. Health Check
curl https://api.prospektlab.com/health
# Expected: 200, {"status": "ok", "service": "oracle-fios"}

# 2. MCP Services
curl https://api.prospektlab.com/api/health/mcp
# Expected: 200, {"all_ok": true, "servers": {...}}

# 3. Chat Endpoint
curl -X POST https://api.prospektlab.com/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "test", "mode": "research"}'
# Expected: 200, valid response

# 4. Frontend
# Open https://app.prospektlab.com in browser
# Check DevTools: console.log(window.__BACKEND_URL)
# Should show your backend URL
```

---

## 🚨 Troubleshooting

### CORS Errors
**Solution:** Update `CORS_ORIGINS` in ECS task definition  
**Reference:** `PRODUCTION_DEPLOYMENT_GUIDE.md` → "CORS Configuration"

### MCP Services Down
**Solution:** Check MCP service URLs and security groups  
**Reference:** `PRODUCTION_VERIFICATION_CHECKLIST.md` → "Network Verification"

### Agent Timeout
**Solution:** Increase `GRAPH_RUN_TIMEOUT_SECONDS` or scale up ECS  
**Reference:** `PRODUCTION_VERIFICATION_CHECKLIST.md` → "Performance Optimization"

### 502 Bad Gateway
**Solution:** Check backend health and ALB configuration  
**Reference:** `PRODUCTION_VERIFICATION_CHECKLIST.md` → "Common Issues & Fixes"

### Frontend Blank
**Solution:** Verify `BACKEND_URL` is set correctly  
**Reference:** `PRODUCTION_VERIFICATION_CHECKLIST.md` → "Frontend Verification"

**See `PRODUCTION_VERIFICATION_CHECKLIST.md` for complete troubleshooting guide**

---

## 🔄 Rollback Procedure

### Quick Rollback (30 seconds)
```bash
aws ecs update-service \
  --cluster prospektlab-prod \
  --service prospektlab-backend \
  --force-new-deployment \
  --region us-east-1
```

### Code Rollback (2-5 minutes)
```bash
git revert HEAD
git push origin production
# GitHub Actions will auto-redeploy with previous version
```

---

## 📊 Deployment Checklist

Before deploying:
- [ ] Read `QUICK_START_DEPLOYMENT.md`
- [ ] Complete `PRE-DEPLOYMENT-CHECKLIST.md`
- [ ] Set all environment variables
- [ ] Test locally with Docker
- [ ] Verify MCP services are running
- [ ] Ensure backups are current

After deploying:
- [ ] Run health checks (see Verification Steps)
- [ ] Test frontend connectivity
- [ ] Check CloudWatch logs
- [ ] Verify all MCP services accessible
- [ ] Monitor for errors (1 hour)
- [ ] Update documentation if needed

---

## 📚 Document Reference

| Document | Purpose | Read Time | Best For |
|----------|---------|-----------|----------|
| `DEPLOYMENT-QUICK-REFERENCE.md` | TL;DR summary | 2 min | Quick lookup |
| `QUICK_START_DEPLOYMENT.md` | Getting started | 10 min | First deployment |
| `PRODUCTION_DEPLOYMENT_GUIDE.md` | Full reference | 30 min | Detailed setup |
| `PRODUCTION_VERIFICATION_CHECKLIST.md` | Testing & troubleshooting | 20 min | Verification |
| `PRE-DEPLOYMENT-CHECKLIST.md` | Pre-flight checks | 30 min | Pre-deployment |
| `DEPLOYMENT-SUMMARY.md` | Changes overview | 10 min | Understanding changes |
| `CHANGE-SUMMARY.md` | Technical details | 15 min | Code review |
| `AWS-DEPLOYMENT-COMMANDS.sh` | CLI reference | Reference | Manual CLI |
| `deploy-production.sh` | Automation script | Reference | Bash deployment |
| `.github/workflows/deploy-production.yml` | GitHub Actions | Reference | CI/CD setup |
| `buildspec-prod.yml` | CodeBuild config | Reference | Enterprise deploy |
| `amplify-buildspec.yml` | Amplify config | Reference | Frontend build |

---

## 🎯 Next Steps (In Order)

### Step 1: Understand (10 minutes)
```
1. Read DEPLOYMENT-QUICK-REFERENCE.md
2. Read QUICK_START_DEPLOYMENT.md
```

### Step 2: Prepare (15 minutes)
```
1. Complete PRE-DEPLOYMENT-CHECKLIST.md
2. Gather environment variables
3. Set up AWS credentials
```

### Step 3: Configure (10 minutes)
```
1. Set CORS_ORIGINS
2. Set MCP URLs
3. Set OpenAI API key
4. Set Amplify backend URL
```

### Step 4: Test (10 minutes)
```
1. Build Docker image locally
2. Test health endpoint
3. Run curl tests
```

### Step 5: Deploy (5-10 minutes)
```
1. Choose deployment method (GitHub Actions recommended)
2. Execute deployment
3. Monitor progress
4. Wait for completion
```

### Step 6: Verify (10 minutes)
```
1. Run health checks
2. Test chat endpoint
3. Verify MCP services
4. Check frontend
5. Monitor logs
```

### Step 7: Monitor (Ongoing)
```
1. Watch CloudWatch logs
2. Check error rates
3. Monitor response times
4. Set up alerts if needed
```

---

## 🎉 Success Criteria

✅ All 4 code files modified
✅ All 10 deployment files created
✅ Documentation complete
✅ Environment variables documented
✅ Deployment methods defined
✅ Verification procedures ready
✅ Troubleshooting guide available
✅ Rollback plan documented

**Your system is ready for production deployment!** 🚀

---

## 📞 Quick Support

### Can't find something?
Use search in these docs:
- General questions → `QUICK_START_DEPLOYMENT.md`
- Configuration issues → `PRODUCTION_DEPLOYMENT_GUIDE.md`
- Errors/problems → `PRODUCTION_VERIFICATION_CHECKLIST.md`
- Technical details → `CHANGE-SUMMARY.md`

### Common Issues Quick Fix
| Problem | Solution | Doc |
|---------|----------|-----|
| CORS error | Update CORS_ORIGINS env var | `PRODUCTION_DEPLOYMENT_GUIDE.md` |
| 502 error | Restart ECS task | `PRODUCTION_VERIFICATION_CHECKLIST.md` |
| Agent timeout | Increase timeout or scale up | `PRODUCTION_VERIFICATION_CHECKLIST.md` |
| Frontend blank | Set BACKEND_URL correctly | `QUICK_START_DEPLOYMENT.md` |
| MCP down | Check service URLs | `PRODUCTION_DEPLOYMENT_GUIDE.md` |

---

## 🔐 Security Notes

1. **Never commit secrets** - Use AWS Secrets Manager or GitHub Secrets
2. **Environment variables** - Use prod values, not dev defaults
3. **CORS carefully** - Only allow Amplify domain
4. **Monitor access** - Check CloudWatch logs regularly
5. **Rotate keys** - Rotate OpenAI API keys periodically
6. **Backup data** - Keep backups before major deployments

---

## 📝 Final Checklist

- [ ] Read `QUICK_START_DEPLOYMENT.md` ✅
- [ ] Complete `PRE-DEPLOYMENT-CHECKLIST.md` ✅
- [ ] Set environment variables ✅
- [ ] Choose deployment method ✅
- [ ] Execute deployment ✅
- [ ] Run verification steps ✅
- [ ] Monitor logs ✅
- [ ] Celebrate success! 🎉✅

---

## 🚀 Ready to Deploy?

```bash
# Start here
cd /path/to/prospektlab
cat QUICK_START_DEPLOYMENT.md

# Or jump straight to deployment
./deploy-production.sh
```

---

**Status: Production Ready ✅**
**Last Updated:** 2024
**All Docs Complete:** 12/12 ✅

Good luck! 🚀
