#!/bin/bash

# ============================================================================
# PROSPEKTLAB PRODUCTION DEPLOYMENT SCRIPT
# Automated deployment to AWS ECS + Amplify
# ============================================================================

set -e  # Exit on any error

# Configuration
export AWS_REGION="us-east-1"
export AWS_ACCOUNT_ID="121488480221"
export ECS_CLUSTER="sleepy-frog-cz9be4"
export ECR_REPO_NAME="prospektlab-backend"
export ECR_REPO_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"
export BACKEND_API_URL="https://api.prospektlab.com"
export AMPLIFY_DOMAIN="https://app.prospektlab.com"
export FRONTEND_URL="https://prospektlab.com"
export CORS_ORIGINS="${FRONTEND_URL},https://www.prospektlab.com,${AMPLIFY_DOMAIN}"

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║          PROSPEKTLAB PRODUCTION DEPLOYMENT SCRIPT                 ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Configuration:"
echo "  AWS Region: $AWS_REGION"
echo "  AWS Account: $AWS_ACCOUNT_ID"
echo "  ECS Cluster: $ECS_CLUSTER"
echo "  ECR Repository: $ECR_REPO_URI"
echo "  Backend URL: $BACKEND_API_URL"
echo "  Frontend URL: $FRONTEND_URL"
echo ""

# ============================================================================
# STEP 1: Fetch backend source and build Docker image
# ============================================================================

echo "═══════════════════════════════════════════════════════════════════════"
echo "STEP 1: Building Docker Image"
echo "═══════════════════════════════════════════════════════════════════════"
echo ""

# Login to ECR
echo "Logging into ECR..."
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin $ECR_REPO_URI
echo "✓ ECR login successful"
echo ""

# Build Docker image
echo "Building Docker image..."
cd /workspaces/prospektlab || cd ~/PROSPEKTLAB || cd .

docker build -t $ECR_REPO_NAME:latest -t $ECR_REPO_NAME:$(date +%Y%m%d-%H%M%S) .
echo "✓ Docker image built"
echo ""

# Tag for ECR
echo "Tagging image for ECR..."
docker tag $ECR_REPO_NAME:latest $ECR_REPO_URI:latest
docker tag $ECR_REPO_NAME:latest $ECR_REPO_URI:$(date +%Y%m%d-%H%M%S)
echo "✓ Image tagged"
echo ""

# Push to ECR
echo "Pushing image to ECR..."
docker push $ECR_REPO_URI:latest
echo "✓ Image pushed to ECR"
echo ""

# ============================================================================
# STEP 2: Create/Update ECS Task Definition
# ============================================================================

echo "═══════════════════════════════════════════════════════════════════════"
echo "STEP 2: Registering ECS Task Definition"
echo "═══════════════════════════════════════════════════════════════════════"
echo ""

# Get existing task definition
TASK_DEF=$(aws ecs describe-task-definition \
  --task-definition finagent-backend \
  --region $AWS_REGION \
  --query 'taskDefinition' 2>/dev/null || echo '{}')

# Update image URI
TASK_DEF=$(echo "$TASK_DEF" | jq --arg IMAGE "$ECR_REPO_URI:latest" '.containerDefinitions[0].image = $IMAGE')

# Update environment variables
TASK_DEF=$(echo "$TASK_DEF" | jq \
  --arg CORS "$CORS_ORIGINS" \
  --arg BACKEND "$BACKEND_API_URL" \
  '.containerDefinitions[0].environment |= . + [
    {name: "CORS_ORIGINS", value: $CORS},
    {name: "FINAGENT_FRONTEND_URL", value: $BACKEND},
    {name: "FRONTEND_URL", value: $BACKEND},
    {name: "APPINSIGHTS_ENABLED", value: "false"}
  ]')

# Clean up task definition
TASK_DEF=$(echo "$TASK_DEF" | jq 'del(.taskDefinitionArn, .revision, .status, .requiresAttributes, .compatibilities, .registeredAt, .registeredBy)')

# Register new task definition
NEW_TASK_DEF_ARN=$(aws ecs register-task-definition \
  --region $AWS_REGION \
  --cli-input-json "$(echo "$TASK_DEF" | jq -c .)" \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text)

echo "✓ Task definition registered: $NEW_TASK_DEF_ARN"
echo ""

# ============================================================================
# STEP 3: Create/Update ECS Service
# ============================================================================

echo "═══════════════════════════════════════════════════════════════════════"
echo "STEP 3: Creating/Updating ECS Service"
echo "═══════════════════════════════════════════════════════════════════════"
echo ""

# Check if service exists
SERVICE_EXISTS=$(aws ecs list-services \
  --cluster $ECS_CLUSTER \
  --region $AWS_REGION \
  --query 'serviceArns[?contains(@, `prospektlab-backend`)]' \
  --output text 2>/dev/null)

if [ -z "$SERVICE_EXISTS" ]; then
  echo "Creating new ECS service..."
  
  # Get VPC and subnet info
  VPC_ID=$(aws ec2 describe-vpcs --region $AWS_REGION --query 'Vpcs[0].VpcId' --output text)
  SUBNETS=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" --region $AWS_REGION --query 'Subnets[*].SubnetId' --output text)
  SECURITY_GROUP=$(aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$VPC_ID" --region $AWS_REGION --query 'SecurityGroups[0].GroupId' --output text)
  
  aws ecs create-service \
    --cluster $ECS_CLUSTER \
    --service-name prospektlab-backend \
    --task-definition $NEW_TASK_DEF_ARN \
    --desired-count 1 \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SECURITY_GROUP],assignPublicIp=ENABLED}" \
    --region $AWS_REGION
  
  echo "✓ ECS service created"
else
  echo "Updating existing ECS service..."
  
  aws ecs update-service \
    --cluster $ECS_CLUSTER \
    --service prospektlab-backend \
    --task-definition $NEW_TASK_DEF_ARN \
    --force-new-deployment \
    --region $AWS_REGION
  
  echo "✓ ECS service updated"
fi

echo ""

# ============================================================================
# STEP 4: Verify Deployment
# ============================================================================

echo "═══════════════════════════════════════════════════════════════════════"
echo "STEP 4: Verifying Deployment"
echo "═══════════════════════════════════════════════════════════════════════"
echo ""

echo "Waiting for service to stabilize..."
sleep 10

SERVICE_INFO=$(aws ecs describe-services \
  --cluster $ECS_CLUSTER \
  --services prospektlab-backend \
  --region $AWS_REGION \
  --query 'services[0]' 2>/dev/null || echo '{}')

DESIRED=$(echo "$SERVICE_INFO" | jq '.desiredCount')
RUNNING=$(echo "$SERVICE_INFO" | jq '.runningCount')

echo "Service Status:"
echo "  Desired: $DESIRED"
echo "  Running: $RUNNING"
echo ""

if [ "$RUNNING" -gt 0 ]; then
  echo "✓ ECS service running successfully!"
else
  echo "ℹ Service is starting. It may take a few minutes to become fully operational."
fi

echo ""
echo "═══════════════════════════════════════════════════════════════════════"
echo "✓ BACKEND DEPLOYMENT COMPLETE"
echo "═══════════════════════════════════════════════════════════════════════"
echo ""
echo "Next steps:"
echo "1. Deploy frontend to Amplify (requires GitHub integration)"
echo "2. Verify backend health at $BACKEND_API_URL/health"
echo "3. Test all application features"
echo ""
