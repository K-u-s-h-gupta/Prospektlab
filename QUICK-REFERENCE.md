# 🚀 ProspektLab Production Deployment - Quick Reference

## Status: ✅ INFRASTRUCTURE READY FOR PRODUCTION

---

## 📋 Three Steps to Production (30-45 minutes)

### Step 1: Deploy Backend (5-10 min)
**Choose ONE option:**

```bash
# Option A: GitHub Actions (RECOMMENDED)
git push origin main
# → Auto-builds, pushes to ECR, deploys to ECS

# Option B: Local Docker
bash deploy-backend-prod.sh

# Option C: AWS CodeBuild
aws codebuild start-build --project-name prospektlab-backend-build
```

### Step 2: Deploy Frontend (5-10 min)
1. Go to: https://console.aws.amazon.com/amplify
2. Click "Create app" → "Host web app"
3. Connect GitHub repo → Select main branch
4. Set env vars:
   - `BACKEND_API_URL=https://api.prospektlab.com`
   - `BACKEND_WS_BASE_URL=https://api.prospektlab.com`
   - `APPINSIGHTS_ENABLED=false`
5. Deploy

### Step 3: Verify (5-10 min)
```bash
# Test backend
curl https://api.prospektlab.com/health

# Check ECS
aws ecs describe-services --cluster sleepy-frog-cz9be4 --services prospektlab-backend

# Visit frontend
https://prospektlab.com
```

---

## 🏗️ Infrastructure Deployed

| Component | Details | Status |
|-----------|---------|--------|
| **ECS Cluster** | sleepy-frog-cz9be4 | ✅ Active |
| **ECS Service** | prospektlab-backend | ✅ Created |
| **Task Def** | finagent-backend:14 | ✅ Ready |
| **ECR Repo** | prospektlab-backend | ✅ Ready |
| **CodeBuild** | prospektlab-backend-build | ✅ Ready |
| **IAM Roles** | CodeBuild + ECS | ✅ Configured |
| **GitHub Actions** | deploy-production.yml | ✅ Ready |

---

## 🎯 Features That Will Be Live

✅ Overview Dashboard  
✅ Portfolio Management  
✅ Watchlist (real-time quotes)  
✅ Market Screener  
✅ Earnings Analysis  
✅ IPO Tracking  
✅ Governance Intelligence  
✅ Content Automation (Insights Studio)  
✅ Chat Agent (Research Gateway)  
✅ Multi-agent Research Engine  

---

## 🔑 AWS Account Details

```
Account ID: 121488480221
Region: us-east-1
VPC: vpc-09d68d298a47c292c
Backend API: https://api.prospektlab.com
```

---

## 📚 Documentation

- `DEPLOYMENT-COMPLETE.md` - Full guide
- `PRODUCTION-DEPLOYMENT-READY.md` - Status report
- `deploy-backend-prod.sh` - Automation script
- `AMPLIFY-DEPLOYMENT.md` - Frontend guide

---

## 🚨 Troubleshooting

**ECS tasks not running?**
```bash
aws logs tail /ecs/finagent-backend --follow
```

**Docker build fails?**
```bash
docker build -t test .
docker run -p 8080:8080 test
```

**Frontend can't reach backend?**
- Check CORS_ORIGINS environment variable
- Verify backend is running: `curl /health`
- Check security groups allow traffic

---

## ⏱️ Timeline

| Step | Duration |
|------|----------|
| Backend Docker Build | 5-10 min |
| Push to ECR | 1-2 min |
| ECS Tasks Start | 2-3 min |
| Frontend Build | 5-10 min |
| Amplify Deploy | 2-5 min |
| **Total** | **~30-45 min** |

---

## ✨ Next Action

**READY TO DEPLOY?**

→ Push to GitHub and GitHub Actions will handle everything!

```bash
git push origin main
```

Then monitor:
- GitHub Actions: https://github.com/your-repo/actions
- ECS Console: https://console.aws.amazon.com/ecs
- Amplify: https://console.aws.amazon.com/amplify

---

**Created:** June 25, 2026  
**Status:** Production Ready ✅  
**All Features:** Deployable 🚀
