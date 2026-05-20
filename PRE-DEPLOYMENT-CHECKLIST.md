# Pre-Deployment Checklist ✅

## Code Changes Verification

- [ ] All Python files compile without errors
- [ ] Backend/api.py has CORS_ORIGINS environment variable
- [ ] finagent/tools/mcp_config.py has environment-driven MCP URLs
- [ ] finagent/api.py has real agent loop integration
- [ ] finagent/gateway/widget.html has backend URL override support
- [ ] All imports are correct (no missing modules)
- [ ] No hardcoded localhost references (except fallback defaults)

## AWS Account Setup

- [ ] AWS Account ID known and verified
- [ ] IAM role for GitHub Actions created (if using CI/CD)
- [ ] ECR repository created: `prospektlab-backend`
- [ ] ECS cluster exists: `prospektlab-prod`
- [ ] ECS service exists: `prospektlab-backend`
- [ ] Load Balancer/ALB configured (if needed)
- [ ] Security groups configured
- [ ] VPC and subnets configured for ECS tasks

## Environment Variables Configured

### ECS Task Definition
- [ ] CORS_ORIGINS = `https://your-amplify-domain.amplifyapp.com`
- [ ] MCP_NSE_INDIA_URL = `http://mcp-nse-service:8001/mcp`
- [ ] MCP_FUNDAMENTALS_URL = `http://mcp-fundamentals-service:8002/mcp`
- [ ] MCP_RESEARCH_URL = `http://mcp-research-service:8003/mcp`
- [ ] MCP_DOCS_URL = `http://mcp-docs-service:8004/mcp`
- [ ] MCP_VALUATION_URL = `http://mcp-valuation-service:8005/mcp`
- [ ] OPENAI_API_KEY = `your-api-key`

### GitHub Secrets (if using Actions)
- [ ] AWS_ROLE_TO_ASSUME configured
- [ ] BACKEND_URL configured
- [ ] AMPLIFY_DOMAIN configured
- [ ] All MCP URLs configured
- [ ] OPENAI_API_KEY configured
- [ ] AMPLIFY_APP_ID configured (optional)
- [ ] SLACK_WEBHOOK_URL configured (optional)

## MCP Services Readiness

- [ ] NSE MCP service running/available
- [ ] Fundamentals MCP service running/available
- [ ] Research MCP service running/available
- [ ] Docs MCP service running/available
- [ ] Valuation MCP service running/available
- [ ] All MCP service URLs accessible from ECS task
- [ ] Security groups allow communication between ECS and MCP services

## Docker Image Readiness

- [ ] Dockerfile builds successfully
- [ ] All dependencies in requirements-finagent.txt are up-to-date
- [ ] No security vulnerabilities in base image
- [ ] Image can start without errors
- [ ] Can verify with: `docker build -t test . && docker run -it test /bin/bash`

## Frontend (Amplify) Readiness

- [ ] Amplify project created
- [ ] GitHub/GitLab repository connected
- [ ] Amplify build settings configured
- [ ] Environment variable BACKEND_API_URL set in Amplify
- [ ] Custom domain configured (if applicable)
- [ ] SSL certificate provisioned
- [ ] Build completes successfully in Amplify

## Network & Security

- [ ] DNS records point to correct endpoints
- [ ] SSL/TLS certificates valid
- [ ] Security groups allow:
  - [ ] HTTPS (443) inbound for frontend users
  - [ ] Port 8080 for ECS tasks
  - [ ] Ports 8001-8005 between ECS and MCP services
- [ ] VPC peering (if needed) configured
- [ ] No hardcoded IP addresses in code
- [ ] Secrets are in AWS Secrets Manager (not in code)

## Documentation

- [ ] PRODUCTION_DEPLOYMENT_GUIDE.md reviewed
- [ ] PRODUCTION_VERIFICATION_CHECKLIST.md reviewed
- [ ] QUICK_START_DEPLOYMENT.md reviewed
- [ ] Team members briefed on deployment process
- [ ] Rollback procedure documented
- [ ] Incident response plan ready

## Testing (Local)

- [ ] Local backend starts: `python -m uvicorn Backend.api:app`
- [ ] Local frontend loads at localhost:3000
- [ ] Can send test query to local backend
- [ ] MCP servers respond locally
- [ ] No errors in browser console

## Pre-Deployment Tests (Staging)

- [ ] Deploy to staging environment first (if available)
- [ ] Run health checks on staging
- [ ] Run full test suite
- [ ] Test agent with real queries
- [ ] Verify all MCP services accessible
- [ ] Check log output for errors/warnings
- [ ] Verify CORS headers

## Backup & Rollback Plan

- [ ] Previous deployment can be restored
- [ ] Database backups current (if applicable)
- [ ] Rollback procedure tested
- [ ] Team aware of rollback steps
- [ ] Monitoring/alerts configured

## Communication

- [ ] Team notified of deployment time
- [ ] Stakeholders briefed on what's deploying
- [ ] Slack/teams channel ready for notifications
- [ ] On-call engineer assigned if needed
- [ ] Status page (if applicable) updated

## Deployment Day

### Pre-Deployment (30 min before)
- [ ] Verify all environment variables are correct
- [ ] Verify no active users (if possible)
- [ ] Ensure MCP services are healthy
- [ ] Ensure backup is current
- [ ] Verify monitoring is active
- [ ] Team assembled and ready

### During Deployment
- [ ] Monitor CloudWatch logs in real-time
- [ ] Check deployment progress in ECS console
- [ ] Run health checks every 30 seconds
- [ ] Be ready to rollback if issues occur
- [ ] Keep team updated on progress

### Post-Deployment (Immediate)
- [ ] Run full verification checklist
- [ ] Test critical user workflows
- [ ] Check error logs for issues
- [ ] Verify performance metrics
- [ ] Send success notification
- [ ] Document any issues

### Post-Deployment (30 min)
- [ ] Monitor for errors/warnings
- [ ] Check for performance degradation
- [ ] Verify all agents are working
- [ ] Confirm MCP services are operational
- [ ] Check frontend looks correct

### Post-Deployment (1 hour+)
- [ ] Stable, no errors
- [ ] Performance normal
- [ ] Users reporting success
- [ ] No incident response needed
- [ ] Update documentation if needed

## Success Criteria

✅ All checks pass before deployment
✅ Deployment completes without errors
✅ Health checks pass (200 OK)
✅ MCP services accessible
✅ Frontend loads and connects to backend
✅ User can submit queries
✅ Agents execute successfully
✅ No errors in logs after 1 hour
✅ Performance is normal

## Rollback Trigger Points

🔴 **IMMEDIATE ROLLBACK IF:**
- Backend returns 5xx errors
- Cannot connect to MCP services
- Frontend shows blank/error page
- CORS errors prevent frontend connection
- Agents timeout on every query
- OpenAI API authentication fails
- Data corruption detected

## Team Checklist

- [ ] Backend Engineer: Code changes verified
- [ ] DevOps Engineer: Infrastructure ready
- [ ] QA Engineer: Tests passed
- [ ] Frontend Engineer: Frontend configured
- [ ] Product Manager: Stakeholders notified
- [ ] Support: Aware of deployment, ready for issues

---

## Last Minute Reminders

1. **Don't deploy on Friday!** 😄 (unless absolutely necessary)
2. **Ensure backups are current**
3. **Have a rollback plan ready**
4. **Keep monitoring open during deployment**
5. **Don't make multiple changes simultaneously**
6. **Test in staging first (if available)**
7. **Communicate with team**
8. **Stay calm, follow the checklist**

---

## After Deployment

- [ ] Update deployment log with:
  - Time of deployment
  - Version/commit deployed
  - Any issues encountered
  - Resolution time
  - Team members involved

- [ ] Close any deployment-related tickets
- [ ] Celebrate success! 🎉
- [ ] Plan post-mortem if needed
- [ ] Gather feedback from team/users
- [ ] Document lessons learned

---

**Status:** Ready / Not Ready ☐
**Approval:** _______________________ (Team Lead)
**Date:** _________________________
