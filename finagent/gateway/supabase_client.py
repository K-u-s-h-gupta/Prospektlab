import os
import httpx
from fastapi import HTTPException

def _get_supabase_url():
    return os.environ.get("SUPABASE_URL", "").rstrip("/")

def _get_supabase_key():
    return os.environ.get("SUPABASE_KEY", "")

def get_headers():
    url = _get_supabase_url()
    key = _get_supabase_key()
    if not url or not key:
        raise HTTPException(status_code=500, detail="SUPABASE_URL and SUPABASE_KEY environment variables are not set.")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }

async def create_admin_user(email: str, password: str, full_name: str, mobile: str = "", avatar_url: str = "", auth_provider: str = "email"):
    """Create a user via Supabase Admin API. This skips email confirmation checks."""
    url = f"{_get_supabase_url()}/auth/v1/admin/users"
    payload = {
        "email": email,
        "password": password,
        "email_confirm": True,
        "user_metadata": {
            "full_name": full_name,
            "mobile": mobile,
            "avatar_url": avatar_url,
            "auth_provider": auth_provider
        }
    }
    
    async with httpx.AsyncClient() as client:
        res = await client.post(url, json=payload, headers=get_headers())
        
        if res.status_code == 422:
            try:
                data = res.json()
                msg = data.get("msg", "") or data.get("message", "")
                if "already registered" in msg.lower() or "already exists" in msg.lower():
                    raise HTTPException(status_code=409, detail="An account with that email already exists.")
                raise HTTPException(status_code=422, detail=msg or "Invalid user data.")
            except HTTPException:
                raise
            except Exception:
                pass
                
        if not res.is_success:
            try:
                data = res.json()
                err = data.get("message") or data.get("msg") or "Failed to create user in Supabase"
            except Exception:
                err = "Failed to create user in Supabase"
            raise HTTPException(status_code=res.status_code, detail=err)
            
        return res.json()

async def update_admin_user_password(user_id: str, new_password: str):
    """Updates a user's password via the Admin API."""
    url = f"{_get_supabase_url()}/auth/v1/admin/users/{user_id}"
    payload = {
        "password": new_password
    }
    
    async with httpx.AsyncClient() as client:
        res = await client.put(url, json=payload, headers=get_headers())
        if not res.is_success:
            raise HTTPException(status_code=res.status_code, detail="Failed to update password in Supabase.")
        return res.json()

async def upsert_profile(user_id: str, email: str, full_name: str, auth_provider: str, mobile: str = "", avatar_url: str = ""):
    """Upserts the user profile into the public.profiles table."""
    url = f"{_get_supabase_url()}/rest/v1/profiles"
    payload = {
        "id": user_id,
        "email": email,
        "full_name": full_name,
        "mobile": mobile,
        "auth_provider": auth_provider,
        "avatar_url": avatar_url
    }
    
    headers = get_headers()
    headers["Prefer"] = "resolution=merge-duplicates"
    
    async with httpx.AsyncClient() as client:
        res = await client.post(url, json=payload, headers=headers)
        if not res.is_success:
            print(f"Failed to upsert profile for {email}: {res.text}")
        return res.is_success

async def authenticate_user(email: str, password: str):
    """Authenticates a user with email and password via Supabase Auth."""
    url = f"{_get_supabase_url()}/auth/v1/token?grant_type=password"
    payload = {
        "email": email,
        "password": password
    }
    
    async with httpx.AsyncClient() as client:
        res = await client.post(url, json=payload, headers=get_headers())
        if not res.is_success:
            if res.status_code == 400:
                raise HTTPException(status_code=401, detail="Invalid email or password.")
            raise HTTPException(status_code=res.status_code, detail="Authentication failed.")
        return res.json()

async def get_user_by_email(email: str):
    """Fetches a user profile from the profiles table."""
    url = f"{_get_supabase_url()}/rest/v1/profiles?email=eq.{email}&select=*"
    
    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=get_headers())
        if not res.is_success:
            return None
            
        data = res.json()
        if data and len(data) > 0:
            return data[0]
        return None

async def update_admin_user_mobile(user_id: str, mobile: str):
    """Updates a user's mobile number via the Admin API (user_metadata only).
    
    We intentionally do NOT set the top-level 'phone' field because Supabase
    rejects it when phone-based auth is not enabled on the project. Storing
    in user_metadata is sufficient for our purposes.
    """
    url = f"{_get_supabase_url()}/auth/v1/admin/users/{user_id}"
    payload = {
        "user_metadata": {
            "mobile": mobile
        }
    }
    
    async with httpx.AsyncClient() as client:
        res = await client.put(url, json=payload, headers=get_headers())
        if not res.is_success:
            detail = "Failed to update mobile number in Supabase."
            try:
                detail = res.json().get("message", detail) or detail
            except Exception:
                pass
            raise HTTPException(status_code=res.status_code, detail=detail)
        return res.json()

def get_user_id_from_auth(email: str) -> str | None:
    """Queries auth.users via GoTrue Admin Users API, falling back to psycopg2 using DB URL."""
    # 1. Query GoTrue Admin Users API using service key
    try:
        import httpx
        url = f"{_get_supabase_url()}/auth/v1/admin/users"
        headers = get_headers()
        # Filter by email using GoTrue's filter query parameter
        resp = httpx.get(url, params={"filter": email}, headers=headers, timeout=10)
        if resp.status_code == 200:
            users = resp.json().get("users", [])
            for u in users:
                if u.get("email") == email:
                    return str(u.get("id"))
    except Exception as e:
        print(f"Error querying auth.users via Supabase Admin API: {e}")

    # 2. Fallback: Query auth.users directly via psycopg2 using DB URL
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        return None
    try:
        import psycopg2
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM auth.users WHERE email = %s;", (email,))
                row = cur.fetchone()
                if row:
                    return str(row[0])
    except Exception as e:
        print(f"Error querying auth.users from database: {e}")
    return None

