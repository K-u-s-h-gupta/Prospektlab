#!/bin/bash
# Production Deployment Script for AWS ECS + Amplify
# Usage: ./deploy-production.sh
# Prerequisites: AWS CLI, jq, proper IAM permissions

set -e

# ============================================================================
# CONFIGURATION - EDIT THESE VALUES
# ============================================================================

# AWS Configuration
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-YOUR_AWS_ACCOUNT_ID}"
ECS_CLUSTER="${ECS_CLUSTER:-prospektlab-prod}"
ECS_SERVICE="${ECS_SERVICE:-prospektlab-backend}"
ECR_REPO_NAME="${ECR_REPO_NAME:-prospektlab-backend}"

# Backend Configuration
BACKEND_URL="${BACKEND_URL:-https://api.prospektlab.com}"  # Your ECS backend URL
AMPLIFY_DOMAIN="${AMPLIFY_DOMAIN:-https://app.prospektlab.com}"  # Your Amplify domain

# MCP Services Configuration
MCP_NSE_URL="${MCP_NSE_URL:-http://mcp-nse-service:8001/mcp}"
MCP_FUNDAMENTALS_URL="${MCP_FUNDAMENTALS_URL:-http://mcp-fundamentals-service:8002/mcp}"
MCP_RESEARCH_URL="${MCP_RESEARCH_URL:-http://mcp-research-service:8003/mcp}"
MCP_DOCS_URL="${MCP_DOCS_URL:-http://mcp-docs-service:8004/mcp}"
MCP_VALUATION_URL="${MCP_VALUATION_URL:-http://mcp-valuation-service:8005/mcp}"

# OpenAI API Key (from environment)
OPENAI_API_KEY="${OPENAI_API_KEY:-}"
APPINSIGHTS_ENABLED="${APPINSIGHTS_ENABLED:-true}"
APPINSIGHTS_CONNECTION_STRING="${APPINSIGHTS_CONNECTION_STRING:-InstrumentationKey=b4797745-6b7f-4d72-894f-768bdc808d3d;IngestionEndpoint=https://centralindia-0.in.applicationinsights.azure.com/;LiveEndpoint=https://centralindia.livediagnostics.monitor.azure.com/;ApplicationId=980e7ddb-6ef5-46e2-b7ae-bb833f3fc8c8}"
APPINSIGHTS_ROLE_NAME="${APPINSIGHTS_ROLE_NAME:-prospektlab-backend}"

# ============================================================================
# VALIDATION
# ============================================================================

echo "🔍 Validating configuration..."

if [ "$AWS_ACCOUNT_ID" == "YOUR_AWS_ACCOUNT_ID" ]; then
	echo "❌ Error: Set AWS_ACCOUNT_ID environment variable"
	exit 1
fi

if [ -z "$OPENAI_API_KEY" ]; then
	echo "❌ Error: Set OPENAI_API_KEY environment variable"
	exit 1
fi

echo "✅ Configuration validated"
echo ""
echo "🚀 Deployment Configuration:"
echo "   AWS Region: $AWS_REGION"
echo "   AWS Account: $AWS_ACCOUNT_ID"
echo "   ECS Cluster: $ECS_CLUSTER"
echo "   ECS Service: $ECS_SERVICE"
echo "   Backend URL: $BACKEND_URL"
echo "   Amplify Domain: $AMPLIFY_DOMAIN"
echo "   App Insights Enabled: $APPINSIGHTS_ENABLED"
echo ""

# ============================================================================
# STEP 1: BUILD DOCKER IMAGE
# ============================================================================

echo "📦 Step 1: Building Docker image..."

docker build -t $ECR_REPO_NAME:latest .
if [ $? -eq 0 ]; then
	echo "✅ Docker image built successfully"
else
	echo "❌ Docker build failed"
	exit 1
fi

# ============================================================================
# STEP 2: TAG AND PUSH TO ECR
# ============================================================================

echo ""
echo "📤 Step 2: Pushing to AWS ECR..."

# Login to ECR
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# Tag image
ECR_IMAGE_URL="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO_NAME:latest"
docker tag $ECR_REPO_NAME:latest $ECR_IMAGE_URL

# Push to ECR
docker push $ECR_IMAGE_URL
if [ $? -eq 0 ]; then
	echo "✅ Image pushed to ECR: $ECR_IMAGE_URL"
else
	echo "❌ ECR push failed"
	exit 1
fi

# ============================================================================
# STEP 3: UPDATE ECS TASK DEFINITION
# ============================================================================

echo ""
echo "🔧 Step 3: Updating ECS Task Definition..."

# Get current task definition
TASK_DEF=$(aws ecs describe-task-definition \
	--task-definition $ECS_SERVICE \
	--region $AWS_REGION \
	--query 'taskDefinition' \
	--output json)

# Create new task definition with updated image and environment variables
NEW_TASK_DEF=$(echo $TASK_DEF | jq \
	--arg IMAGE "$ECR_IMAGE_URL" \
	--arg CORS_ORIGINS "$AMPLIFY_DOMAIN" \
	--arg MCP_NSE "$MCP_NSE_URL" \
	--arg MCP_FUNDAMENTALS "$MCP_FUNDAMENTALS_URL" \
	--arg MCP_RESEARCH "$MCP_RESEARCH_URL" \
	--arg MCP_DOCS "$MCP_DOCS_URL" \
	--arg MCP_VALUATION "$MCP_VALUATION_URL" \
	--arg OPENAI_KEY "$OPENAI_API_KEY" \
	--arg APPINSIGHTS_ENABLED "$APPINSIGHTS_ENABLED" \
	--arg APPINSIGHTS_CONNECTION_STRING "$APPINSIGHTS_CONNECTION_STRING" \
	--arg APPINSIGHTS_ROLE_NAME "$APPINSIGHTS_ROLE_NAME" \
	'.containerDefinitions[0].image = $IMAGE |
	 .containerDefinitions[0].environment = (
	   .containerDefinitions[0].environment // [] |
	   map(select(.name != "CORS_ORIGINS" and 
				  .name != "MCP_NSE_INDIA_URL" and 
				  .name != "MCP_FUNDAMENTALS_URL" and 
				  .name != "MCP_RESEARCH_URL" and 
				  .name != "MCP_DOCS_URL" and 
				  .name != "MCP_VALUATION_URL" and 
				  .name != "OPENAI_API_KEY" and
				  .name != "APPINSIGHTS_ENABLED" and
				  .name != "APPINSIGHTS_CONNECTION_STRING" and
				  .name != "APPINSIGHTS_ROLE_NAME")) +
	   [
		 {name: "CORS_ORIGINS", value: $CORS_ORIGINS},
		 {name: "MCP_NSE_INDIA_URL", value: $MCP_NSE},
		 {name: "MCP_FUNDAMENTALS_URL", value: $MCP_FUNDAMENTALS},
		 {name: "MCP_RESEARCH_URL", value: $MCP_RESEARCH},
		 {name: "MCP_DOCS_URL", value: $MCP_DOCS},
		 {name: "MCP_VALUATION_URL", value: $MCP_VALUATION},
		 {name: "OPENAI_API_KEY", value: $OPENAI_KEY},
		 {name: "APPINSIGHTS_ENABLED", value: $APPINSIGHTS_ENABLED},
		 {name: "APPINSIGHTS_CONNECTION_STRING", value: $APPINSIGHTS_CONNECTION_STRING},
		 {name: "APPINSIGHTS_ROLE_NAME", value: $APPINSIGHTS_ROLE_NAME}
	   ]
	 ) |
	 del(.taskDefinitionArn, .revision, .status, .requiresAttributes, .compatibilities, .registeredAt, .registeredBy)'
)

# Register new task definition
REGISTERED=$(aws ecs register-task-definition \
	--region $AWS_REGION \
	--cli-input-json "$NEW_TASK_DEF")

NEW_TASK_DEF_ARN=$(echo $REGISTERED | jq -r '.taskDefinition.taskDefinitionArn')
echo "✅ Task definition registered: $NEW_TASK_DEF_ARN"

# ============================================================================
# STEP 4: UPDATE ECS SERVICE
# ============================================================================

echo ""
echo "🚀 Step 4: Updating ECS service..."

aws ecs update-service \
	--cluster $ECS_CLUSTER \
	--service $ECS_SERVICE \
	--task-definition $NEW_TASK_DEF_ARN \
	--region $AWS_REGION \
	--force-new-deployment

echo "✅ ECS service updated"

# ============================================================================
# STEP 5: WAIT FOR DEPLOYMENT
# ============================================================================

echo ""
echo "⏳ Step 5: Waiting for deployment to complete (this may take 2-5 minutes)..."

WAIT_TIME=0
MAX_WAIT=600  # 10 minutes

while [ $WAIT_TIME -lt $MAX_WAIT ]; do
	DEPLOYMENT_STATUS=$(aws ecs describe-services \
		--cluster $ECS_CLUSTER \
		--services $ECS_SERVICE \
		--region $AWS_REGION \
		--query 'services[0].deployments' \
		--output json)

	ACTIVE_COUNT=$(echo $DEPLOYMENT_STATUS | jq 'length')

	if [ "$ACTIVE_COUNT" == "1" ]; then
		echo "✅ Deployment complete!"
		break
	fi

	echo "   Waiting... ($WAIT_TIME/$MAX_WAIT seconds)"
	sleep 10
	WAIT_TIME=$((WAIT_TIME + 10))
done

if [ $WAIT_TIME -ge $MAX_WAIT ]; then
	echo "⚠️  Deployment timeout. Check AWS Console for status."
fi

# ============================================================================
# STEP 6: HEALTH CHECK
# ============================================================================

echo ""
echo "🏥 Step 6: Running health checks..."

# Get the backend ALB/service endpoint
SERVICE_INFO=$(aws ecs describe-services \
	--cluster $ECS_CLUSTER \
	--services $ECS_SERVICE \
	--region $AWS_REGION \
	--query 'services[0]' \
	--output json)

echo ""
echo "Service Information:"
echo $SERVICE_INFO | jq '{
	desiredCount: .desiredCount,
	runningCount: .runningCount,
	pendingCount: .pendingCount,
	deployments: [.deployments[] | {
		taskDefinition: .taskDefinition,
		desiredCount: .desiredCount,
		runningCount: .runningCount,
		status: .status
	}]
}'

echo ""
echo "⏳ Attempting health check (waiting for tasks to start)..."
sleep 10

# Try health check
HEALTH_URL="${BACKEND_URL}/health"
echo "📡 Testing: $HEALTH_URL"

for i in {1..10}; do
	RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" $HEALTH_URL 2>/dev/null || echo "000")

	if [ "$RESPONSE" == "200" ]; then
		echo "✅ Backend is healthy!"
		break
	else
		echo "   Attempt $i/10: HTTP $RESPONSE (waiting...)"
		sleep 5
	fi
done

# ============================================================================
# STEP 7: UPDATE AMPLIFY (if needed)
# ============================================================================

echo ""
echo "🌐 Step 7: Amplify Frontend Deployment..."
echo "   ⚠️  Note: Frontend deployment must be done via AWS Amplify Console or CI/CD"
echo ""
echo "   Option 1: Using AWS Amplify Console"
echo "   - Go to AWS Amplify Console"
echo "   - Select 'prospektlab' app"
echo "   - Ensure build settings have BACKEND_API_URL environment variable set to:"
echo "     $BACKEND_URL"
echo ""
echo "   Option 2: Using AWS CLI"
echo "   aws amplify start-deployment --app-id YOUR_AMPLIFY_APP_ID --branch-name main --region $AWS_REGION"
echo ""

# ============================================================================
# COMPLETION
# ============================================================================

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "✅ DEPLOYMENT COMPLETE!"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Backend URL: $BACKEND_URL"
echo "Frontend URL: $AMPLIFY_DOMAIN"
echo ""
echo "Next Steps:"
echo "1. Verify health check: curl $BACKEND_URL/health"
echo "2. Check MCP servers: curl $BACKEND_URL/api/health/mcp"
echo "3. Test chat: curl -X POST $BACKEND_URL/api/chat -H 'Content-Type: application/json' -d '{\"message\":\"test\",\"mode\":\"research\"}'"
echo "4. Deploy frontend (see options above)"
echo "5. Monitor CloudWatch logs for errors"
echo ""
