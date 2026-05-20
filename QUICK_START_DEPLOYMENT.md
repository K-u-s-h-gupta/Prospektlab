# 🚀 Quick Start Production Deployment

## Option 1: Automated Deployment (Recommended)

### Prerequisites
- Git repository pushed to GitHub/GitLab
- AWS account with proper permissions
- GitHub Secrets configured (see below)

### Step 1: Configure GitHub Secrets

Go to: `Settings → Secrets and variables → Actions → New repository secret`

Add these secrets:
```
AWS_ROLE_TO_ASSUME          → arn:aws:iam::YOUR_ACCOUNT_ID:role/GitHubActionsRole
BACKEND_URL                 → https://api.prospektlab.com
AMPLIFY_DOMAIN              → https://app.prospektlab.com
MCP_NSE_URL                 → http://mcp-nse-service:8001/mcp
MCP_FUNDAMENTALS_URL        → http://mcp-fundamentals-service:8002/mcp
MCP_RESEARCH_URL            → http://mcp-research-service:8003/mcp
MCP_DOCS_URL                → http://mcp-docs-service:8004/mcp
MCP_VALUATION_URL           → http://mcp-valuation-service:8005/mcp
OPENAI_API_KEY              → your-openai-key
AMPLIFY_APP_ID              → your-amplify-app-id (optional)
SLACK_WEBHOOK_URL           → your-slack-webhook (optional)
```

### Step 2: Push to Production

```bash
# Option A: Merge to production branch
git checkout production
git merge main
git push origin production

# Option B: Trigger manually
# Go to GitHub Actions → Deploy to Production → Run workflow
```

The workflow will:
- ✅ Build Docker image
- ✅ Push to ECR
- ✅ Update ECS task definition
- ✅ Deploy to ECS
- ✅ Wait for deployment
- ✅ Run health checks
- ✅ Send Slack notification

**Deployment time:** ~5-10 minutes

---

## Option 2: Manual Deployment (Using Script)

### Step 1: Set Environment Variables

```bash
# Create .env file or export variables
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=YOUR_ACCOUNT_ID
export ECS_CLUSTER=prospektlab-prod
export ECS_SERVICE=prospektlab-backend
export BACKEND_URL=https://api.prospektlab.com
export AMPLIFY_DOMAIN=https://app.prospektlab.com
export OPENAI_API_KEY=your-key
```

### Step 2: Run Deployment Script

```bash
chmod +x deploy-production.sh
./deploy-production.sh
```

The script will:
- ✅ Build Docker image
- ✅ Login to ECR
- ✅ Push to ECR
- ✅ Update task definition
- ✅ Update ECS service
- ✅ Wait for deployment
- ✅ Run health checks

**Deployment time:** ~5-10 minutes

---

## Option 3: Manual AWS CLI Commands

### Step 1: Build and Push Image

```bash
# Set variables
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=us-east-1
ECR_REPO=prospektlab-backend

# Build
docker build -t $ECR_REPO:latest .

# Tag for ECR
docker tag $ECR_REPO:latest $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO:latest

# Login to ECR
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# Push
docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO:latest
```

### Step 2: Update ECS Service

```bash
# Update task definition (use buildspec-prod.yml as reference)
aws ecs update-service \
  --cluster prospektlab-prod \
  --service prospektlab-backend \
  --force-new-deployment \
  --region $AWS_REGION
```

### Step 3: Monitor Deployment

```bash
# Watch real-time progress
watch -n 5 'aws ecs describe-services \
  --cluster prospektlab-prod \
  --services prospektlab-backend \
  --region us-east-1 \
  --query "services[0].{running: runningCount, desired: desiredCount, pending: pendingCount}"'
```

---

## Verification After Deployment

### 1. Check Backend Health

```bash
curl https://api.prospektlab.com/health
# Expected: {"status": "ok", "service": "oracle-fios"}
```

### 2. Check MCP Connectivity

```bash
curl https://api.prospektlab.com/api/health/mcp
# Expected: {"all_ok": true, "servers": {...}}
```

### 3. Test Chat Endpoint

```bash
curl -X POST https://api.prospektlab.com/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is RELIANCE?", "mode": "research"}'
```

### 4. Check Frontend

```bash
# Open browser
https://app.prospektlab.com

# Check DevTools console
console.log(window.__BACKEND_URL)
# Should print: https://api.prospektlab.com
```

---

## Troubleshooting

### ❌ Deployment Stuck at "Waiting for deployment"

```bash
# Check task status
aws ecs describe-tasks \
  --cluster prospektlab-prod \
  --tasks <TASK_ARN> \
  --region us-east-1

# Check logs
aws logs tail /ecs/prospektlab-backend --follow --region us-east-1
```

### ❌ 502 Bad Gateway / Connection Refused

**Check 1:** Is backend running?
```bash
curl -v https://api.prospektlab.com/health
```

**Check 2:** Is ALB/security group allowing traffic?
```bash
# In AWS Console: EC2 → Security Groups → Check inbound rules
```

**Check 3:** Are MCP services reachable?
```bash
curl https://api.prospektlab.com/api/health/mcp
```

### ❌ CORS Error in Frontend

**Fix:** Update CORS_ORIGINS environment variable
```bash
aws ecs update-service \
  --cluster prospektlab-prod \
  --service prospektlab-backend \
  --region us-east-1 \
  --force-new-deployment
# Then update task definition with correct CORS_ORIGINS
```

### ❌ MCP Servers Show "ok": false

**Check 1:** Verify service names/URLs
```bash
# Inside ECS task
curl http://mcp-nse-service:8001/health
```

**Check 2:** Check security groups allow traffic between services

**Check 3:** Restart MCP services in ECS

---

## Rollback (If Something Breaks)

### Quick Rollback

```bash
# Redeploy previous version
aws ecs update-service \
  --cluster prospektlab-prod \
  --service prospektlab-backend \
  --task-definition prospektlab-backend:PREVIOUS_NUMBER \
  --force-new-deployment \
  --region us-east-1
```

### Full Rollback

```bash
# Git rollback
git revert HEAD
git push origin production

# This will automatically trigger GitHub Actions to redeploy with previous code
```

---

## Monitoring Deployment

### CloudWatch Logs
```bash
# View real-time logs
aws logs tail /ecs/prospektlab-backend --follow --region us-east-1

# View specific error
aws logs tail /ecs/prospektlab-backend --follow --filter-pattern "ERROR"
```

### ECS Console
- Go to AWS Console → ECS → Clusters → prospektlab-prod → Services → prospektlab-backend
- Watch "Deployments" tab for progress

### Slack Notifications (if configured)
- Automatic notifications sent on deployment success/failure
- Click link to view GitHub Actions details

---

## Performance Tuning (After Deployment)

### If responses are slow:

1. **Increase ECS task resources**
   ```bash
   # Update task definition with higher CPU/memory
   ```

2. **Check MCP server latency**
   ```bash
   curl https://api.prospektlab.com/api/health/mcp | jq '.servers'
   ```

3. **Scale to 2 instances**
   ```bash
   aws ecs update-service \
	 --cluster prospektlab-prod \
	 --service prospektlab-backend \
	 --desired-count 2 \
	 --region us-east-1
   ```

---

## Useful AWS CLI Commands

### Check deployment status
```bash
aws ecs describe-services --cluster prospektlab-prod --services prospektlab-backend --region us-east-1
```

### View recent tasks
```bash
aws ecs list-tasks --cluster prospektlab-prod --region us-east-1
```

### View ECR images
```bash
aws ecr list-images --repository-name prospektlab-backend --region us-east-1
```

### Get service events (errors)
```bash
aws ecs describe-services --cluster prospektlab-prod --services prospektlab-backend --region us-east-1 \
  --query 'services[0].events[*].[createdAt,message]' --output table
```

---

## What's Deployed

After successful deployment:

| Component | Location | Status |
|-----------|----------|--------|
| **Backend** | ECS (prospektlab-prod) | ✅ Running on 8080 |
| **MCP Servers** | ECS (internal) | ✅ Running on 8001-8005 |
| **Frontend** | Amplify | ✅ Connected to Backend |
| **Database** | (if used) | - |
| **Cache** | (if used) | - |

---

## Next Steps

1. ✅ Monitor logs for errors
2. ✅ Run load testing (if needed)
3. ✅ Set up CloudWatch alarms
4. ✅ Document any custom deployments
5. ✅ Schedule regular backups

---

## Need Help?

Check these files for more details:
- `PRODUCTION_DEPLOYMENT_GUIDE.md` — Full configuration
- `PRODUCTION_VERIFICATION_CHECKLIST.md` — Testing steps
- `AWS-DEPLOYMENT-COMMANDS.sh` — All CLI commands
- `.github/workflows/deploy-production.yml` — GitHub Actions workflow

**Support:** Check CloudWatch logs and AWS Console for diagnostics
