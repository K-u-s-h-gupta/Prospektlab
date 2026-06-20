# AWS Production Deployment Commands
# Use these commands to deploy to ECS and Amplify

# ============================================================================
# PREREQUISITE: Set Environment Variables
# ============================================================================

export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export ECS_CLUSTER=prospektlab-prod
export ECS_SERVICE=prospektlab-backend
export ECR_REPO=prospektlab-backend
export BACKEND_URL=https://api.prospektlab.com
export AMPLIFY_DOMAIN=https://app.prospektlab.com
export FRONTEND_PRIMARY_URL=https://prospektlab.com
export CORS_ORIGINS="${FRONTEND_PRIMARY_URL},https://www.prospektlab.com,${AMPLIFY_DOMAIN}"
export OPENAI_API_KEY=your-openai-key-here

# Verify
echo "AWS_ACCOUNT_ID: $AWS_ACCOUNT_ID"
echo "AWS_REGION: $AWS_REGION"
echo "ECS_CLUSTER: $ECS_CLUSTER"
echo "ECS_SERVICE: $ECS_SERVICE"

# ============================================================================
# STEP 1: BUILD AND PUSH DOCKER IMAGE
# ============================================================================

# Option A: Using buildspec.yml (CodeBuild)
aws codebuild start-build \
  --project-name prospektlab-backend \
  --region $AWS_REGION

# Option B: Manual docker build and push
ECR_REPO_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}"

# Login to ECR
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin $ECR_REPO_URI

# Build image
docker build -t $ECR_REPO:latest .

# Tag image
docker tag $ECR_REPO:latest $ECR_REPO_URI:latest
docker tag $ECR_REPO:latest $ECR_REPO_URI:$(date +%Y%m%d-%H%M%S)

# Push to ECR
docker push $ECR_REPO_URI:latest
docker push $ECR_REPO_URI:$(date +%Y%m%d-%H%M%S)

# ============================================================================
# STEP 2: UPDATE ECS TASK DEFINITION WITH ENVIRONMENT VARIABLES
# ============================================================================

# Get current task definition
aws ecs describe-task-definition \
  --task-definition $ECS_SERVICE \
  --region $AWS_REGION \
  --query 'taskDefinition' > /tmp/task-def.json

# Create new task definition (using jq)
jq '.containerDefinitions[0].image = "'$ECR_REPO_URI':latest" |
	.containerDefinitions[0].environment += [
	  {name: "CORS_ORIGINS", value: "'$CORS_ORIGINS'"},
	  {name: "FINAGENT_FRONTEND_URL", value: "'$FRONTEND_PRIMARY_URL'"},
	  {name: "FRONTEND_URL", value: "'$FRONTEND_PRIMARY_URL'"},
	  {name: "MCP_NSE_INDIA_URL", value: "http://mcp-nse-service:8001/mcp"},
	  {name: "MCP_FUNDAMENTALS_URL", value: "http://mcp-fundamentals-service:8002/mcp"},
	  {name: "MCP_RESEARCH_URL", value: "http://mcp-research-service:8003/mcp"},
	  {name: "MCP_DOCS_URL", value: "http://mcp-docs-service:8004/mcp"},
	  {name: "MCP_VALUATION_URL", value: "http://mcp-valuation-service:8005/mcp"},
	  {name: "OPENAI_API_KEY", value: "'$OPENAI_API_KEY'"}
	] |
	del(.taskDefinitionArn, .revision, .status, .requiresAttributes, .compatibilities, .registeredAt, .registeredBy)' \
  /tmp/task-def.json > /tmp/new-task-def.json

# Register new task definition
NEW_TASK_DEF_ARN=$(aws ecs register-task-definition \
  --region $AWS_REGION \
  --cli-input-json file:///tmp/new-task-def.json \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text)

echo "New task definition: $NEW_TASK_DEF_ARN"

# ============================================================================
# STEP 3: UPDATE ECS SERVICE TO USE NEW TASK DEFINITION
# ============================================================================

aws ecs update-service \
  --cluster $ECS_CLUSTER \
  --service $ECS_SERVICE \
  --task-definition $NEW_TASK_DEF_ARN \
  --force-new-deployment \
  --region $AWS_REGION

echo "✅ ECS service updated. Deployment starting..."

# ============================================================================
# STEP 4: MONITOR DEPLOYMENT PROGRESS
# ============================================================================

# Watch deployment status
watch -n 5 'aws ecs describe-services \
  --cluster '$ECS_CLUSTER' \
  --services '$ECS_SERVICE' \
  --region '$AWS_REGION' \
  --query "services[0].{
	desiredCount: desiredCount,
	runningCount: runningCount,
	pendingCount: pendingCount,
	deployments: deployments[*].{
	  status: status,
	  desiredCount: desiredCount,
	  runningCount: runningCount,
	  taskDefinition: taskDefinition
	}
  }"'

# Alternative: One-time check
aws ecs describe-services \
  --cluster $ECS_CLUSTER \
  --services $ECS_SERVICE \
  --region $AWS_REGION \
  --query 'services[0]' \
  --output json | jq '.'

# ============================================================================
# STEP 5: VERIFY DEPLOYMENT
# ============================================================================

# Get service endpoint (if using ALB)
aws elbv2 describe-target-groups \
  --region $AWS_REGION \
  --query 'TargetGroups[?contains(TargetGroupArn, `prospektlab`)].TargetGroupArn' \
  --output text

# Test health endpoint
curl -v https://api.prospektlab.com/health

# Test MCP health
curl -v https://api.prospektlab.com/api/health/mcp

# Test chat endpoint
curl -X POST https://api.prospektlab.com/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Test query", "mode": "research"}'

# ============================================================================
# STEP 6: DEPLOY FRONTEND TO AMPLIFY
# ============================================================================

# Get Amplify app ID
AMPLIFY_APP_ID=$(aws amplify list-apps \
  --region $AWS_REGION \
  --query 'apps[?name==`prospektlab`].appId' \
  --output text)

echo "Amplify App ID: $AMPLIFY_APP_ID"

# Trigger frontend deployment
aws amplify start-deployment \
  --app-id $AMPLIFY_APP_ID \
  --branch-name main \
  --region $AWS_REGION

# Monitor frontend build
aws amplify get-branch \
  --app-id $AMPLIFY_APP_ID \
  --branch-name main \
  --region $AWS_REGION \
  --query 'branch.{
	branchName: branchName,
	status: status,
	lastDeployTime: lastDeployTime
  }'

# ============================================================================
# STEP 7: UPDATE AMPLIFY ENVIRONMENT VARIABLES
# ============================================================================

# Update Amplify build settings with backend URL
aws amplify update-app \
  --app-id $AMPLIFY_APP_ID \
  --region $AWS_REGION \
  --environment-variables \
	BACKEND_API_URL=$BACKEND_URL

# ============================================================================
# STEP 8: ROLLBACK (if needed)
# ============================================================================

# Get previous task definition
PREVIOUS_TASK_DEF=$(aws ecs describe-services \
  --cluster $ECS_CLUSTER \
  --services $ECS_SERVICE \
  --region $AWS_REGION \
  --query 'services[0].taskDefinition' \
  --output text | sed 's/:[0-9]*$//' | sed 's/:/-/g' | awk -F- '{$NF=$NF-1; print}' | sed 's/-/:/g')

# Rollback to previous version
aws ecs update-service \
  --cluster $ECS_CLUSTER \
  --service $ECS_SERVICE \
  --task-definition $PREVIOUS_TASK_DEF \
  --force-new-deployment \
  --region $AWS_REGION

echo "✅ Rollback initiated"

# ============================================================================
# STEP 9: VIEW LOGS
# ============================================================================

# Get log group
LOG_GROUP="/ecs/$ECS_SERVICE"

# View recent logs
aws logs tail $LOG_GROUP --follow --region $AWS_REGION

# View specific container logs
aws logs tail "$LOG_GROUP" --follow --since 1h --region $AWS_REGION | grep -i "error\|warning"

# ============================================================================
# STEP 10: SCALE SERVICE (if needed)
# ============================================================================

# Scale to 2 tasks
aws ecs update-service \
  --cluster $ECS_CLUSTER \
  --service $ECS_SERVICE \
  --desired-count 2 \
  --region $AWS_REGION

# Scale to 1 task
aws ecs update-service \
  --cluster $ECS_CLUSTER \
  --service $ECS_SERVICE \
  --desired-count 1 \
  --region $AWS_REGION

# ============================================================================
# USEFUL QUERIES
# ============================================================================

# List all ECS services
aws ecs list-services --cluster $ECS_CLUSTER --region $AWS_REGION

# Get service details
aws ecs describe-services \
  --cluster $ECS_CLUSTER \
  --services $ECS_SERVICE \
  --region $AWS_REGION

# List task definitions
aws ecs list-task-definitions --region $AWS_REGION --query 'taskDefinitionArns'

# Get task definition details
aws ecs describe-task-definition \
  --task-definition $ECS_SERVICE:1 \
  --region $AWS_REGION

# List tasks in service
aws ecs list-tasks \
  --cluster $ECS_CLUSTER \
  --service-name $ECS_SERVICE \
  --region $AWS_REGION

# Describe specific task
aws ecs describe-tasks \
  --cluster $ECS_CLUSTER \
  --tasks <TASK_ARN> \
  --region $AWS_REGION

# Get ECR images
aws ecr list-images --repository-name $ECR_REPO --region $AWS_REGION

# Get ECR image details
aws ecr describe-images \
  --repository-name $ECR_REPO \
  --region $AWS_REGION

# View service events (errors/warnings)
aws ecs describe-services \
  --cluster $ECS_CLUSTER \
  --services $ECS_SERVICE \
  --region $AWS_REGION \
  --query 'services[0].events' \
  --output json | jq '.[] | {createdAt, message}'
