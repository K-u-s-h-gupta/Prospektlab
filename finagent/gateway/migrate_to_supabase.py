"""
Supabase Migration Script for ProspektLab
Consolidates JSON files (manual signup) and SQLite (Google signup) users into Supabase Auth and Database.

Usage:
  export SUPABASE_URL="your-supabase-url"
  export SUPABASE_KEY="your-supabase-service-role-key"
  python migrate_to_supabase.py
"""

import os
import json
import sqlite3
import urllib.request
import urllib.error
from pathlib import Path

# Configurations
USERS_DIR = Path.home() / ".finagent" / "users"
DB_PATH = Path(__file__).resolve().parent.parent / "prospektlab.db"

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")  # Must be SERVICE ROLE KEY to bypass verification SMTP

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: SUPABASE_URL and SUPABASE_KEY (service role key) environment variables are required.")
    exit(1)

# Format the URL properly
SUPABASE_URL = SUPABASE_URL.rstrip('/')

def make_request(url_path, method="POST", data=None):
    url = f"{SUPABASE_URL}{url_path}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    
    req_data = None
    if data is not None:
        req_data = json.dumps(data).encode("utf-8")
        
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode("utf-8")
            if res_body:
                return json.loads(res_body)
            return {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        raise Exception(f"HTTP {e.code}: {err_body}")

def create_auth_user(email, password, user_metadata):
    # Uses Supabase Auth Admin API
    payload = {
        "email": email,
        "password": password,
        "email_confirm": True,
        "user_metadata": user_metadata
    }
    return make_request("/auth/v1/admin/users", method="POST", data=payload)

def upsert_profile(user_id, email, full_name, auth_provider, mobile="", avatar_url=""):
    # Uses PostgREST API
    payload = {
        "id": user_id,
        "email": email,
        "full_name": full_name,
        "mobile": mobile,
        "auth_provider": auth_provider,
        "avatar_url": avatar_url
    }
    # For upsert, we need a special header in PostgREST
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }
    
    url = f"{SUPABASE_URL}/rest/v1/profiles"
    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as response:
            return True
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        raise Exception(f"HTTP {e.code}: {err_body}")


def migrate_manual_users():
    print("Migrating manual users from JSON files...")
    if not USERS_DIR.is_dir():
        print(f"No manual users directory found at {USERS_DIR}. Skipping.")
        return

    for path in USERS_DIR.glob("*.json"):
        try:
            user_data = json.loads(path.read_text(encoding="utf-8"))
            email = user_data.get("email")
            name = user_data.get("name", "Researcher")
            mobile = user_data.get("mobile", "")
            
            print(f"Creating Auth user: {email}...")
            
            user_metadata = {
                "full_name": name,
                "mobile": mobile,
                "auth_provider": "email"
            }
            
            res = create_auth_user(email, "TemporaryMigrationPassword123!", user_metadata)
            user_id = res.get("id")
            
            upsert_profile(user_id, email, name, "email", mobile=mobile)
            
            print(f"Successfully migrated manual user: {email}")
        except Exception as e:
            print(f"Failed to migrate manual user from {path.name}: {e}")


def migrate_google_users():
    print("Migrating Google users from SQLite database...")
    if not DB_PATH.is_file():
        print(f"No SQLite database found at {DB_PATH}. Skipping.")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users")
        rows = cursor.fetchall()
        conn.close()
    except Exception as e:
        print(f"Failed to read SQLite database: {e}")
        return

    for row in rows:
        email = row["email"]
        full_name = row["full_name"]
        avatar_url = row["avatar_url"]
        
        print(f"Creating Google Auth user: {email}...")
        try:
            user_metadata = {
                "full_name": full_name,
                "avatar_url": avatar_url,
                "auth_provider": "google"
            }
            
            import secrets
            random_pw = secrets.token_urlsafe(32) + "A1!"
            
            res = create_auth_user(email, random_pw, user_metadata)
            user_id = res.get("id")
            
            upsert_profile(user_id, email, full_name, "google", avatar_url=avatar_url)
            
            print(f"Successfully migrated Google user: {email}")
        except Exception as e:
            print(f"Failed to migrate Google user {email}: {e}")


if __name__ == "__main__":
    migrate_manual_users()
    migrate_google_users()
    print("Migration finished!")
