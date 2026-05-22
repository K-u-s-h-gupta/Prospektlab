# deploy-backend.ps1
# Automates the build and deployment of the FinAgent backend to AWS ECS Fargate

$projectName = "finagent-backend"
$stackName = "$projectName-stack"

Write-Host "1. Deploying AWS CloudFormation Stack (this sets up VPC, ALB, ECS, ECR, and CodeBuild)..." -ForegroundColor Cyan
aws cloudformation deploy `
  --template-file deployment/fargate-backend.yml `
  --stack-name $stackName `
  --capabilities CAPABILITY_IAM `
  --parameter-overrides ProjectName=$projectName

if ($LASTEXITCODE -ne 0) {
    Write-Error "CloudFormation deployment failed!"
    exit 1
}

Write-Host "Fetching stack outputs..." -ForegroundColor Cyan
$outputs = aws cloudformation describe-stacks --stack-name $stackName --query "Stacks[0].Outputs" --output json | ConvertFrom-Json

$bucketName = ($outputs | Where-Object { $_.OutputKey -eq "SourceBucketName" }).OutputValue
$buildProject = ($outputs | Where-Object { $_.OutputKey -eq "CodeBuildProjectName" }).OutputValue
$albDns = ($outputs | Where-Object { $_.OutputKey -eq "ALBDNS" }).OutputValue
$httpApiUrl = ($outputs | Where-Object { $_.OutputKey -eq "HttpApiUrl" }).OutputValue

Write-Host "Source Bucket: $bucketName" -ForegroundColor Green
Write-Host "CodeBuild Project: $buildProject" -ForegroundColor Green
Write-Host "ALB DNS URL: http://$albDns" -ForegroundColor Green
Write-Host "API Gateway HTTPS URL: $httpApiUrl" -ForegroundColor Green

Write-Host "2. Creating local deployment package (backend.zip)..." -ForegroundColor Cyan
python deployment/zip_backend.py

Write-Host "3. Uploading source archive to S3..." -ForegroundColor Cyan
aws s3 cp backend.zip s3://$bucketName/backend.zip

if ($LASTEXITCODE -ne 0) {
    Write-Error "S3 Upload failed!"
    exit 1
}

Write-Host "4. Triggering AWS CodeBuild to build Docker image and deploy to ECS Fargate..." -ForegroundColor Cyan
$buildInfo = aws codebuild start-build --project-name $buildProject --query "build.id" --output text

Write-Host "Build successfully triggered!" -ForegroundColor Green
Write-Host "CodeBuild Build ID: $buildInfo" -ForegroundColor Green
Write-Host "Your backend will build in the cloud and deploy to ECS Fargate automatically." -ForegroundColor Yellow
Write-Host "Once the build completes (takes ~5-7 minutes), your API will be live at: $httpApiUrl/health" -ForegroundColor Green
