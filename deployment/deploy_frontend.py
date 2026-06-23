import os

import zipfile

import json

import subprocess

import tempfile

import urllib.request

import time

import sys



# Constants

APP_NAME = "finagent-frontend"

APP_ID = os.getenv("AMPLIFY_APP_ID", "d1z5h6v6ty54e7")

BRANCH_NAME = "production"

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")

ZIP_PATH = "frontend.zip"

API_GATEWAY_URL = os.getenv(

    "API_GATEWAY_URL",

    "https://wr7fle8bc1.execute-api.ap-south-1.amazonaws.com",

)





def resolve_frontend_dist_dir() -> str:

    candidates = [

        os.getenv("FRONTEND_DIST_DIR", ""),

        os.path.join("Frontend", "dist"),

        os.path.join("frontend", "dist"),

        os.path.join("Frontend", "app", "dist"),

    ]

    for candidate in candidates:

        if candidate and os.path.isdir(candidate):

            return candidate

    return os.path.join("Frontend", "dist")



# Custom rewrite/redirect rules

CUSTOM_RULES = [

    {

        "source": "/robots.txt",

        "target": "/robots.txt",

        "status": "200"

    },

    {

        "source": "/sitemap.xml",

        "target": f"{API_GATEWAY_URL}/sitemap.xml",

        "status": "200"

    },

    {

        "source": "/unsubscribe",

        "target": "/unsubscribe/index.html",

        "status": "200"

    },

    {

        "source": "/unsubscribe/",

        "target": "/unsubscribe/index.html",

        "status": "200"

    },

    {

        "source": "/insights/organic-traffic-platform",

        "target": "/insights/organic-traffic-platform/index.html",

        "status": "200"

    },

    {

        "source": "/insights/organic-traffic-platform/",

        "target": "/insights/organic-traffic-platform/index.html",

        "status": "200"

    },

    {

        "source": "/insights/research",

        "target": f"{API_GATEWAY_URL}/insights/research",

        "status": "200"

    },

    {

        "source": "/insights/research/",

        "target": f"{API_GATEWAY_URL}/insights/research",

        "status": "200"

    },

    {

        "source": "/insights/strategy",

        "target": "/insights/strategy/index.html",

        "status": "200"

    },

    {

        "source": "/insights/strategy/",

        "target": "/insights/strategy/index.html",

        "status": "200"

    },

    {

        "source": "/insights/<*>",

        "target": f"{API_GATEWAY_URL}/insights/<*>",

        "status": "200"

    },

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

        "source": "/memos",

        "target": f"{API_GATEWAY_URL}/memos",

        "status": "200"

    },

    {

        "source": "/memos/<*>",

        "target": f"{API_GATEWAY_URL}/memos/<*>",

        "status": "200"

    },

    {

        "source": "/config",

        "target": f"{API_GATEWAY_URL}/config",

        "status": "200"

    },

    {

        "source": "/config/<*>",

        "target": f"{API_GATEWAY_URL}/config/<*>",

        "status": "200"

    },

    {

        "source": "/capabilities",

        "target": f"{API_GATEWAY_URL}/capabilities",

        "status": "200"

    },

    {

        "source": "/capabilities/<*>",

        "target": f"{API_GATEWAY_URL}/capabilities/<*>",

        "status": "200"

    },

    {

        "source": "/health",

        "target": f"{API_GATEWAY_URL}/health",

        "status": "200"

    },

    {

        "source": "/health/<*>",

        "target": f"{API_GATEWAY_URL}/health/<*>",

        "status": "200"

    },

    {

        "source": "/public",

        "target": f"{API_GATEWAY_URL}/public",

        "status": "200"

    },

    {

        "source": "/public/<*>",

        "target": f"{API_GATEWAY_URL}/public/<*>",

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

        "source": "/screener/<*>",

        "target": f"{API_GATEWAY_URL}/screener/<*>",

        "status": "200"

    },

    {

        "source": "/api/portfolio/<*>",

        "target": f"{API_GATEWAY_URL}/api/portfolio/<*>",

        "status": "200"

    },

    {

        "source": "/api/content/<*>",

        "target": f"{API_GATEWAY_URL}/api/content/<*>",

        "status": "200"

    },

    {

        "source": "/api/outreach/<*>",

        "target": f"{API_GATEWAY_URL}/api/outreach/<*>",

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

        "source": "/login",

        "target": "/index.html",

        "status": "200"

    },

    {

        "source": "/signup",

        "target": "/index.html",

        "status": "200"

    },

    {

        "source": "/profile",

        "target": "/index.html",

        "status": "200"

    },

    {

        "source": "/settings",

        "target": "/index.html",

        "status": "200"

    },

    {

        "source": "/app",

        "target": "/index.html",

        "status": "200"

    },

    {

        "source": "/landing",

        "target": "/index.html",

        "status": "200"

    },

    {

        "source": "</^[^.]+$|\\.(?!(css|gif|ico|jpg|js|png|txt|svg|woff|woff2|ttf|map|json|webp|xml)$)([^.]+$)/>",

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



def create_frontend_zip():

    print("1. Creating frontend.zip deployment package...")

    frontend_dist_dir = resolve_frontend_dist_dir()

    if not os.path.isdir(frontend_dist_dir):

        raise Exception(

            f"Frontend build output not found at {frontend_dist_dir}. "

            "Run `npm run build` inside Frontend first."

        )



    with zipfile.ZipFile(ZIP_PATH, 'w', zipfile.ZIP_DEFLATED) as zipf:

        for root, _, files in os.walk(frontend_dist_dir):

            for file in files:

                file_path = os.path.join(root, file)

                arcname = os.path.relpath(file_path, frontend_dist_dir)

                zipf.write(file_path, arcname)

                print(f"  Added {file_path} as {arcname}")



    print(f"Frontend package created successfully: {ZIP_PATH}")



def deploy():

    # Create frontend zip

    create_frontend_zip()

    

    # Target the Mumbai Amplify app explicitly so we never hit the old us-east-1 app.

    print("2. Using configured AWS Amplify app...")

    app_id = APP_ID

    print(f"  App ID: {app_id}")

        

    # Apply custom rewrite rules

    print("3. Applying redirect/rewrite rules for backend proxying...")

    rules_path = os.path.join(tempfile.gettempdir(), "prospektlab-amplify-rules-frontend.json")

    with open(rules_path, "w") as f:

        json.dump(CUSTOM_RULES, f, indent=2)

        

    try:

        run_cmd(f'aws amplify update-app --app-id {app_id} --region {AWS_REGION} --custom-rules file://{rules_path}')

        print("  Redirect/rewrite rules applied successfully!")

    finally:

        if os.path.exists(rules_path):

            try:

                os.remove(rules_path)

            except OSError:

                pass

            

    # Deploy to both main and production branches

    branches = ["main", "production"]

    for branch_name in branches:

        print(f"\n=== Deploying to Branch: {branch_name} ===")

        # Check if branch exists

        branch_exists = False

        try:

            branches_json = run_cmd(f"aws amplify list-branches --app-id {app_id} --region {AWS_REGION}")

            branches_list = json.loads(branches_json).get("branches", [])

            for branch in branches_list:

                if branch.get("branchName") == branch_name:

                    branch_exists = True

                    print(f"  Branch '{branch_name}' already exists.")

                    break

        except Exception as e:

            print(f"Error checking branch: {e}")

            

        if not branch_exists:

            print(f"  Creating branch '{branch_name}'...")

            run_cmd(f"aws amplify create-branch --app-id {app_id} --branch-name {branch_name} --region {AWS_REGION}")

            print(f"  Branch '{branch_name}' created.")

            

        # Trigger manual deployment

        print(f"  Initiating manual deployment for '{branch_name}'...")

        deploy_json = run_cmd(f"aws amplify create-deployment --app-id {app_id} --branch-name {branch_name} --region {AWS_REGION}")

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

        run_cmd(f"aws amplify start-deployment --app-id {app_id} --branch-name {branch_name} --job-id {job_id} --region {AWS_REGION}")

        print("  Deployment started.")



        # Poll deployment status

        print("  Polling deployment status...")

        while True:

            status_json = run_cmd(f"aws amplify get-job --app-id {app_id} --branch-name {branch_name} --job-id {job_id} --region {AWS_REGION}")

            job = json.loads(status_json).get("job", {})

            status = job.get("summary", {}).get("status")

            print(f"    Current Status: {status}")

            

            if status in ["SUCCEEDED", "SUCCEED", "FAILED"]:

                break

            time.sleep(5)

            

        if status in ["SUCCEEDED", "SUCCEED"]:

            print(f"=== DEPLOYMENT SUCCESSFUL FOR {branch_name.upper()} ===")

            app_domain = f"https://{branch_name}.{app_id}.amplifyapp.com"

            print(f"Your frontend is live at: {app_domain}")

        else:

            print(f"=== DEPLOYMENT FAILED FOR {branch_name.upper()} ===")

            

    # Clean up local zip

    if os.path.exists(ZIP_PATH):

        try:

            os.remove(ZIP_PATH)

        except OSError:

            pass



if __name__ == "__main__":

    deploy()

