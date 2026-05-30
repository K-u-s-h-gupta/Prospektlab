import os
import zipfile
import json
import subprocess
import urllib.request
import time
import sys

# Constants
APP_NAME = "finagent-frontend"
ZIP_PATH = "react_frontend.zip"
API_GATEWAY_URL = "https://pp2nutjt0l.execute-api.us-east-1.amazonaws.com"
DIST_DIR = os.path.join("Frontend", "app", "dist")

CUSTOM_RULES = [
    {
        "source": "/auth/<*>",
        "target": f"{API_GATEWAY_URL}/auth/<*>",
        "status": "200"
    },
    {
        "source": "/sessions/<*>",
        "target": f"{API_GATEWAY_URL}/sessions/<*>",
        "status": "200"
    },
    {
        "source": "/memos<*>",
        "target": f"{API_GATEWAY_URL}/memos<*>",
        "status": "200"
    },
    {
        "source": "/config<*>",
        "target": f"{API_GATEWAY_URL}/config<*>",
        "status": "200"
    },
    {
        "source": "/capabilities<*>",
        "target": f"{API_GATEWAY_URL}/capabilities<*>",
        "status": "200"
    },
    {
        "source": "/health<*>",
        "target": f"{API_GATEWAY_URL}/health<*>",
        "status": "200"
    },
    {
        "source": "/memory/<*>",
        "target": f"{API_GATEWAY_URL}/memory/<*>",
        "status": "200"
    },
    {
        "source": "/research/<*>",
        "target": f"{API_GATEWAY_URL}/research/<*>",
        "status": "200"
    },
    {
        "source": "/chat/<*>",
        "target": f"{API_GATEWAY_URL}/chat/<*>",
        "status": "200"
    },
    {
        "source": "/portfolio/<*>",
        "target": f"{API_GATEWAY_URL}/portfolio/<*>",
        "status": "200"
    },
    {
        "source": "/api/portfolio/<*>",
        "target": f"{API_GATEWAY_URL}/api/portfolio/<*>",
        "status": "200"
    },
    {
        "source": "/user/<*>",
        "target": f"{API_GATEWAY_URL}/user/<*>",
        "status": "200"
    },
    {
        "source": "/market/<*>",
        "target": f"{API_GATEWAY_URL}/market/<*>",
        "status": "200"
    },
    {
        "source": "</^[^.]+$|\\.(?!(css|gif|ico|jpg|js|png|txt|svg|woff|woff2|ttf|map|json|webp)$)([^.]+$)/>",
        "target": "/index.html",
        "status": "200"
    }
]

def run_cmd(cmd):
    """Run shell command and return stdout as string."""
    result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise Exception(f"Command failed: {cmd}\nError: {result.stderr}")
    return result.stdout.strip()

def create_zip():
    print(f"1. Creating {ZIP_PATH} from {DIST_DIR}...")
    
    # Inject API URL into env-config.js in the build output directory
    env_config_path = os.path.join(DIST_DIR, "env-config.js")
    with open(env_config_path, "w") as f:
        f.write(f'window.__BACKEND_URL = "{API_GATEWAY_URL}"; window.__CONFIG__ = {{ apiBase: "{API_GATEWAY_URL}", environment: "production" }};\n')
    print("  Injected backend URL into env-config.js")

    if os.path.exists(ZIP_PATH):
        try:
            os.remove(ZIP_PATH)
        except OSError:
            pass
            
    with zipfile.ZipFile(ZIP_PATH, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(DIST_DIR):
            for file in files:
                filePath = os.path.join(root, file)
                archivePath = os.path.relpath(filePath, DIST_DIR)
                zipf.write(filePath, archivePath)
                print(f"  Added {filePath} as {archivePath}")

    print(f"React frontend package created successfully: {ZIP_PATH}")

def deploy():
    # Create zip from build output
    create_zip()
    
    # Check if app already exists
    print("2. Checking for existing AWS Amplify app...")
    app_id = None
    try:
        apps_json = run_cmd("aws amplify list-apps")
        apps = json.loads(apps_json).get("apps", [])
        for app in apps:
            if app.get("name") == APP_NAME:
                app_id = app.get("appId")
                print(f"  Found existing Amplify app: {APP_NAME} (ID: {app_id})")
                break
    except Exception as e:
        print(f"Error listing apps: {e}")
        sys.exit(1)
        
    if not app_id:
        print(f"Error: App {APP_NAME} not found on AWS Amplify!")
        sys.exit(1)
        
    # Apply custom rewrite rules for SPA router and API proxying
    print("3. Applying redirect/rewrite rules for SPA routing & backend proxying...")
    rules_path = "amplify-rules-react.json"
    with open(rules_path, "w") as f:
        json.dump(CUSTOM_RULES, f, indent=2)
        
    try:
        run_cmd(f'aws amplify update-app --app-id {app_id} --custom-rules file://{rules_path}')
        print("  Redirect/rewrite rules applied successfully!")
    finally:
        if os.path.exists(rules_path):
            os.remove(rules_path)
            
    # Deploy to both main and production branches
    branches = ["main", "production"]
    for branch_name in branches:
        print(f"\n=== Deploying React App to Branch: {branch_name} ===")
        
        # Trigger manual deployment
        print(f"  Initiating manual deployment for '{branch_name}'...")
        deploy_json = run_cmd(f"aws amplify create-deployment --app-id {app_id} --branch-name {branch_name}")
        deploy_data = json.loads(deploy_json)
        
        job_id = deploy_data.get("jobId")
        zip_upload_url = deploy_data.get("zipUploadUrl")
        
        if not job_id or not zip_upload_url:
            print(f"Error: Could not retrieve jobId or zipUploadUrl for branch '{branch_name}'!")
            continue

        # Upload zip file
        print(f"  Uploading frontend archive for '{branch_name}'...")
        with open(ZIP_PATH, "rb") as f:
            data = f.read()
            
        req = urllib.request.Request(
            zip_upload_url,
            data=data,
            headers={'Content-Type': 'application/zip'},
            method='PUT'
        )
        
        try:
            with urllib.request.urlopen(req) as response:
                print(f"  Zip archive uploaded successfully for '{branch_name}'!")
        except Exception as e:
            print(f"Error uploading archive: {e}")
            continue

        # Start deployment
        print(f"  Starting Amplify deployment for '{branch_name}'...")
        run_cmd(f"aws amplify start-deployment --app-id {app_id} --branch-name {branch_name} --job-id {job_id}")
        print("  Deployment started.")

        # Poll deployment status
        print("  Polling deployment status...")
        while True:
            status_json = run_cmd(f"aws amplify get-job --app-id {app_id} --branch-name {branch_name} --job-id {job_id}")
            job = json.loads(status_json).get("job", {})
            status = job.get("summary", {}).get("status")
            print(f"    Current Status: {status}")
            
            if status in ["SUCCEEDED", "SUCCEED", "FAILED"]:
                break
            time.sleep(5)
            
        if status in ["SUCCEEDED", "SUCCEED"]:
            print(f"=== DEPLOYMENT SUCCESSFUL FOR {branch_name.upper()} ===")
            app_domain = f"https://{branch_name}.{app_id}.amplifyapp.com"
            print(f"Your React SPA frontend is live at: {app_domain}")
        else:
            print(f"=== DEPLOYMENT FAILED FOR {branch_name.upper()} ===")
            
    # Clean up local zip
    if os.path.exists(ZIP_PATH):
        os.remove(ZIP_PATH)

if __name__ == "__main__":
    deploy()
