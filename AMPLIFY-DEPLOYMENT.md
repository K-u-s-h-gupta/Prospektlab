# Amplify App Configuration for ProspektLab Frontend
# Deploy this app to AWS Amplify Console

## Prerequisites:
- GitHub repo connected to Amplify
- AWS Account with Amplify service access

## Build Settings:

Environment Variables:
- BACKEND_DEFAULT_API_URL: https://wr7fle8bc1.execute-api.us-east-1.amazonaws.com
- BACKEND_API_URL: https://api.prospektlab.com
- BACKEND_CANONICAL_URL: https://api.prospektlab.com
- BACKEND_WS_BASE_URL: https://api.prospektlab.com
- APPINSIGHTS_ENABLED: false

Build Specification: Use amplify-buildspec.yml in root

## Deployment Steps:

1. In AWS Amplify Console:
   - Click "New app" → "Host web app"
   - Connect GitHub repo (prospektlab)
   - Select production branch
   - Set environment variables above
   - Deploy

2. Or via AWS CLI:
   ```bash
   aws amplify create-app \
     --name prospektlab \
     --repository https://github.com/your-org/prospektlab \
     --platform WEB
   ```

## Domain Configuration:
- Production Domain: prospektlab.com
- Amplify Domain: app.prospektlab.com
- Redirect http → https
- Enable CloudFront caching
