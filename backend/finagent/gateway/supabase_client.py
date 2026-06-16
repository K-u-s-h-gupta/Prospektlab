import os
import ast
import json
import logging
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import HTTPException


_SUPABASE_TIMEOUT = httpx.Timeout(12.0, connect=5.0)
logger = logging.getLogger("finagent.gateway.supabase_client")


def _httpx_trust_env() -> bool:
    raw = os.environ.get("FINAGENT_HTTP_TRUST_ENV", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


_HTTPX_TRUST_ENV = _httpx_trust_env()


def _supabase_async_client(**kwargs):
    return httpx.AsyncClient(
        timeout=_SUPABASE_TIMEOUT,
        trust_env=_HTTPX_TRUST_ENV,
        **kwargs,
    )

def _get_supabase_url():
    return os.environ.get("SUPABASE_URL", "").rstrip("/")

def _get_supabase_key():
    return os.environ.get("SUPABASE_KEY", "")

def _get_outreach_supabase_url():
    return (os.environ.get("OUTREACH_SUPABASE_URL", "") or _get_supabase_url()).rstrip("/")

def _get_outreach_supabase_key():
    return os.environ.get("OUTREACH_SUPABASE_KEY", "") or _get_supabase_key()

def get_headers(*, outreach: bool = False):
    url = _get_outreach_supabase_url() if outreach else _get_supabase_url()
    key = _get_outreach_supabase_key() if outreach else _get_supabase_key()
    if not url or not key:
        if outreach:
            raise HTTPException(
                status_code=500,
                detail="Outreach Supabase environment variables are not set.",
            )
        raise HTTPException(status_code=500, detail="SUPABASE_URL and SUPABASE_KEY environment variables are not set.")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }

def _auth_timeout_error() -> HTTPException:
    return HTTPException(status_code=504, detail="Authentication service timed out. Please try again.")


def _parse_payload_json(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    text = str(raw)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    # Backward compatibility for legacy rows inserted with str(dict)
    try:
        parsed = ast.literal_eval(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}

async def create_admin_user(
    email: str,
    password: str,
    full_name: str,
    mobile: str = "",
    avatar_url: str = "",
    auth_provider: str = "email",
    referral_source: str = "",
    email_confirm: bool = True,
):
    """Create a user via Supabase Admin API."""
    mobile_clean = str(mobile or "").strip()
    referral_source_clean = str(referral_source or "").strip()
    url = f"{_get_supabase_url()}/auth/v1/admin/users"
    base_payload = {
        "email": email,
        "password": password,
        "email_confirm": email_confirm,
        "user_metadata": {
            "full_name": full_name,
            "mobile": mobile_clean,
            "phone": mobile_clean,
            "avatar_url": avatar_url,
            "auth_provider": auth_provider,
            "referral_source": referral_source_clean,
        }
    }
    payload = {**base_payload, "phone": mobile_clean} if mobile_clean else base_payload
    
    try:
        async with _supabase_async_client() as client:
            res = await client.post(url, json=payload, headers=get_headers())
            if not res.is_success and mobile_clean:
                # Some projects reject top-level phone when phone auth is disabled.
                # Retry once without top-level phone while preserving metadata.
                res = await client.post(url, json=base_payload, headers=get_headers())
    except httpx.TimeoutException:
        raise _auth_timeout_error()
        
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
    
    try:
        async with _supabase_async_client() as client:
            res = await client.put(url, json=payload, headers=get_headers())
    except httpx.TimeoutException:
        raise _auth_timeout_error()
    if not res.is_success:
        raise HTTPException(status_code=res.status_code, detail="Failed to update password in Supabase.")
    return res.json()

async def upsert_profile(
    user_id: str,
    email: str,
    full_name: str,
    auth_provider: str,
    mobile: str = "",
    avatar_url: str = "",
    referral_source: str = "",
):
    """Upserts the user profile into the public.profiles table.

    Returns the saved profile row. Raises HTTPException on failure.
    """
    url = f"{_get_supabase_url()}/rest/v1/profiles"
    mobile_clean = str(mobile or "").strip()
    referral_source_clean = str(referral_source or "").strip()
    base_payload = {
        "id": user_id,
        "email": email,
        "full_name": full_name,
        "auth_provider": auth_provider,
        "avatar_url": avatar_url,
    }

    headers = get_headers()
    headers["Prefer"] = "resolution=merge-duplicates,return=representation"
    params = {"on_conflict": "id"}

    async def _post_profile(payload: dict) -> httpx.Response:
        async with _supabase_async_client() as client:
            return await client.post(url, json=payload, headers=headers, params=params)

    candidate_payloads = []
    if mobile_clean and referral_source_clean:
        candidate_payloads.extend([
            {**base_payload, "mobile": mobile_clean, "referral_source": referral_source_clean},
            {**base_payload, "phone": mobile_clean, "referral_source": referral_source_clean},
            {**base_payload, "mobile": mobile_clean},
            {**base_payload, "phone": mobile_clean},
        ])
    elif mobile_clean:
        candidate_payloads.extend([
            {**base_payload, "mobile": mobile_clean},
            {**base_payload, "phone": mobile_clean},
        ])
    elif referral_source_clean:
        candidate_payloads.append({**base_payload, "referral_source": referral_source_clean})
    candidate_payloads.append(base_payload)

    def _column_missing(text: str, col: str) -> bool:
        # Match both error phrasings: raw Postgres ("column profiles.X does not
        # exist") and PostgREST's schema-cache error PGRST204 ("Could not find
        # the 'X' column of 'profiles' in the schema cache").
        return (
            f"column profiles.{col} does not exist" in text
            or (f"'{col}'" in text and "schema cache" in text)
        )

    res = None
    last_error_text = ""
    for payload in candidate_payloads:
        try:
            res = await _post_profile(payload)
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Profile save timed out. Please retry.")

        if res.is_success:
            break

        last_error_text = res.text or ""
        missing_mobile = _column_missing(last_error_text, "mobile")
        missing_phone = _column_missing(last_error_text, "phone")
        missing_referral = _column_missing(last_error_text, "referral_source")
        if not (missing_mobile or missing_phone or missing_referral):
            break

    if res is None:
        raise HTTPException(status_code=500, detail="Profile save did not return a response.")

    if not res.is_success:
        detail = "Failed to save profile details in Supabase."
        try:
            payload_error = res.json()
            detail = payload_error.get("message") or payload_error.get("msg") or detail
        except Exception:
            if res.text:
                detail = res.text
        raise HTTPException(status_code=res.status_code, detail=detail)

    data = res.json()
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    return payload

async def authenticate_user(email: str, password: str):
    """Authenticates a user with email and password via Supabase Auth."""
    url = f"{_get_supabase_url()}/auth/v1/token?grant_type=password"
    payload = {
        "email": email,
        "password": password
    }
    
    try:
        async with _supabase_async_client() as client:
            res = await client.post(url, json=payload, headers=get_headers())
    except httpx.TimeoutException:
        raise _auth_timeout_error()
    if not res.is_success:
        if res.status_code == 400:
            raise HTTPException(status_code=401, detail="Invalid email or password.")
        raise HTTPException(status_code=res.status_code, detail="Authentication failed.")
    return res.json()

async def get_user_by_email(email: str):
    """Fetches a user profile from the profiles table."""
    url = f"{_get_supabase_url()}/rest/v1/profiles"
    params = {
        "email": f"eq.{email}",
        "select": "*",
    }
    
    try:
        async with _supabase_async_client() as client:
            res = await client.get(url, headers=get_headers(), params=params)
    except httpx.TimeoutException:
        return None
    if not res.is_success:
        return None

    data = res.json()
    if data and len(data) > 0:
        return data[0]
    return None

async def update_admin_user_mobile(user_id: str, mobile: str):
    """Updates a user's mobile number via the Admin API.

    We try writing top-level `phone` plus user_metadata for projects with phone auth.
    If top-level phone is not accepted, we gracefully fall back to metadata-only.
    """
    mobile_clean = str(mobile or "").strip()
    url = f"{_get_supabase_url()}/auth/v1/admin/users/{user_id}"
    payload = {
        "phone": mobile_clean,
        "user_metadata": {
            "mobile": mobile_clean,
            "phone": mobile_clean,
        }
    }
    
    try:
        async with _supabase_async_client() as client:
            res = await client.put(url, json=payload, headers=get_headers())
    except httpx.TimeoutException:
        raise _auth_timeout_error()

    if not res.is_success:
        fallback_payload = {
            "user_metadata": {
                "mobile": mobile_clean,
                "phone": mobile_clean,
            }
        }
        try:
            async with _supabase_async_client() as client:
                res = await client.put(url, json=fallback_payload, headers=get_headers())
        except httpx.TimeoutException:
            raise _auth_timeout_error()

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
        url = f"{_get_supabase_url()}/auth/v1/admin/users"
        headers = get_headers()
        # Filter by email using GoTrue's filter query parameter
        resp = httpx.get(url, params={"filter": email}, headers=headers, timeout=_SUPABASE_TIMEOUT, trust_env=_HTTPX_TRUST_ENV)
        if resp.status_code == 200:
            users = resp.json().get("users", [])
            for u in users:
                if u.get("email") == email:
                    return str(u.get("id"))
    except httpx.TimeoutException as exc:
        logger.warning("Supabase admin users lookup timed out for %s: %s", email, exc)
    except Exception as e:
        logger.warning("Error querying auth.users via Supabase Admin API for %s: %s", email, e)

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
        logger.warning("Error querying auth.users from database for %s: %s", email, e)
    return None


# â”€â”€ Supabase-backed state store (with local SQLite fallback) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def store_verification_code(email: str, code: str, type_: str = "signup") -> bool:
    """Store verification code in Supabase (or local SQLite fallback)."""
    url = f"{_get_supabase_url()}/rest/v1/verification_codes"
    payload = {
        "email": email.lower().strip(),
        "code": code,
        "type": type_,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        async with _supabase_async_client() as client:
            headers = get_headers()
            headers["Prefer"] = "resolution=merge-duplicates"
            res = await client.post(url, json=payload, headers=headers)
            if res.is_success:
                return True
    except Exception:
        pass
    # Fallback to local SQLite
    from finagent.gateway.state_store import store_verification_code as local_store
    local_store(email, code, type_)
    return True


async def verify_and_consume_code(email: str, code: str, type_: str = "signup", ttl_seconds: int = 600) -> bool:
    """Verify and consume a verification code from Supabase (or local SQLite fallback)."""
    url = f"{_get_supabase_url()}/rest/v1/verification_codes"
    try:
        async with _supabase_async_client() as client:
            headers = get_headers()
            # Query for the code
            params = {"email": f"eq.{email.lower().strip()}", "type": f"eq.{type_}", "select": "code,created_at"}
            res = await client.get(url, params=params, headers=headers)
            if res.is_success:
                data = res.json()
                if data and len(data) > 0:
                    stored = data[0]
                    created_at = datetime.fromisoformat(stored["created_at"].replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - created_at).total_seconds()
                    if age > ttl_seconds:
                        # Delete expired
                        await client.delete(url, params=params, headers=headers)
                        return False
                    if stored["code"] == code.strip():
                        # Delete consumed
                        await client.delete(url, params=params, headers=headers)
                        return True
                    return False
    except Exception:
        pass
    # Fallback to local SQLite
    from finagent.gateway.state_store import verify_and_consume_code as local_verify
    return local_verify(email, code, type_, ttl_seconds)


async def store_pending_extraction(review_id: str, tenant_id: str, payload: dict) -> bool:
    """Store pending extraction in Supabase (or local SQLite fallback)."""
    url = f"{_get_supabase_url()}/rest/v1/pending_extractions"
    payload_row = {
        "review_id": review_id,
        "tenant_id": tenant_id,
        "payload_json": json.dumps(payload, ensure_ascii=False),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        async with _supabase_async_client() as client:
            headers = get_headers()
            headers["Prefer"] = "resolution=merge-duplicates"
            res = await client.post(url, json=payload_row, headers=headers)
            if res.is_success:
                return True
    except Exception:
        pass
    # Fallback to local SQLite
    from finagent.gateway.state_store import store_pending_extraction as local_store
    local_store(review_id, tenant_id, payload)
    return True


async def get_pending_extraction(review_id: str) -> dict | None:
    """Get pending extraction from Supabase (or local SQLite fallback)."""
    url = f"{_get_supabase_url()}/rest/v1/pending_extractions"
    try:
        async with _supabase_async_client() as client:
            headers = get_headers()
            params = {"review_id": f"eq.{review_id}", "select": "tenant_id,payload_json"}
            res = await client.get(url, params=params, headers=headers)
            if res.is_success:
                data = res.json()
                if data and len(data) > 0:
                    return {"tenant_id": data[0]["tenant_id"], "extraction": _parse_payload_json(data[0]["payload_json"])}
    except Exception:
        pass
    # Fallback to local SQLite
    from finagent.gateway.state_store import get_pending_extraction as local_get
    return local_get(review_id)


async def get_pending_extractions_by_tenant(tenant_id: str) -> list[dict]:
    """Get pending extractions for a tenant from Supabase (or local SQLite fallback)."""
    url = f"{_get_supabase_url()}/rest/v1/pending_extractions"
    try:
        async with _supabase_async_client() as client:
            headers = get_headers()
            params = {"tenant_id": f"eq.{tenant_id}", "select": "review_id,payload_json"}
            res = await client.get(url, params=params, headers=headers)
            if res.is_success:
                data = res.json()
                return [{"review_id": d["review_id"], **_parse_payload_json(d.get("payload_json"))} for d in data]
    except Exception:
        pass
    # Fallback to local SQLite
    from finagent.gateway.state_store import get_pending_extractions_by_tenant as local_get
    return local_get(tenant_id)


async def delete_pending_extraction(review_id: str) -> bool:
    """Delete pending extraction from Supabase (or local SQLite fallback)."""
    url = f"{_get_supabase_url()}/rest/v1/pending_extractions"
    try:
        async with _supabase_async_client() as client:
            headers = get_headers()
            params = {"review_id": f"eq.{review_id}"}
            res = await client.delete(url, params=params, headers=headers)
            if res.is_success:
                return True
    except Exception:
        pass
    # Fallback to local SQLite
    from finagent.gateway.state_store import delete_pending_extraction as local_delete
    local_delete(review_id)
    return True


# â”€â”€ Token revocation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def store_outreach_unsubscribe(
    email: str,
    reason: str = "unsubscribe",
    source: str = "public_page",
    note: str = "",
):
    """Store a durable outreach unsubscribe in Supabase (or local SQLite fallback)."""
    normalized = email.lower().strip()
    url = f"{_get_outreach_supabase_url()}/rest/v1/outreach_unsubscribes"
    payload = {
        "email": normalized,
        "reason": (reason or "unsubscribe").strip() or "unsubscribe",
        "source": (source or "public_page").strip() or "public_page",
        "note": (note or "").strip(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        async with _supabase_async_client() as client:
            headers = get_headers(outreach=True)
            headers["Prefer"] = "resolution=merge-duplicates,return=representation"
            params = {"on_conflict": "email"}
            res = await client.post(url, json=payload, headers=headers, params=params)
            if res.is_success:
                data = res.json()
                if isinstance(data, list) and data:
                    return data[0]
                if isinstance(data, dict):
                    return data
                return payload
    except Exception:
        pass

    from finagent.gateway.state_store import store_outreach_unsubscribe as local_store

    return local_store(normalized, payload["reason"], payload["source"], payload["note"])


async def list_outreach_unsubscribes() -> list[dict]:
    """Return all outreach unsubscribes from Supabase (or local SQLite fallback)."""
    url = f"{_get_outreach_supabase_url()}/rest/v1/outreach_unsubscribes"
    try:
        async with _supabase_async_client() as client:
            headers = get_headers(outreach=True)
            params = {
                "select": "email,reason,source,note,created_at,updated_at",
                "order": "updated_at.desc,email.asc",
            }
            res = await client.get(url, params=params, headers=headers)
            if res.is_success:
                data = res.json()
                if isinstance(data, list):
                    return data
    except Exception:
        pass

    from finagent.gateway.state_store import list_outreach_unsubscribes as local_list

    return local_list()


async def revoke_token(jti: str, expires_at: float) -> bool:
    """Revoke a token via Supabase (or local SQLite fallback)."""
    url = f"{_get_supabase_url()}/rest/v1/revoked_tokens"
    payload = {
        "jti": jti,
        "revoked_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
    }
    try:
        async with _supabase_async_client() as client:
            headers = get_headers()
            headers["Prefer"] = "resolution=merge-duplicates"
            res = await client.post(url, json=payload, headers=headers)
            if res.is_success:
                return True
    except Exception:
        pass
    # Fallback to local SQLite
    from finagent.gateway.state_store import revoke_token as local_revoke
    local_revoke(jti, expires_at)
    return True


async def is_token_revoked(jti: str) -> bool:
    """Check if a token is revoked via Supabase (or local SQLite fallback)."""
    url = f"{_get_supabase_url()}/rest/v1/revoked_tokens"
    try:
        async with _supabase_async_client() as client:
            headers = get_headers()
            params = {"jti": f"eq.{jti}", "select": "jti"}
            res = await client.get(url, params=params, headers=headers)
            if res.is_success:
                data = res.json()
                return len(data) > 0
    except Exception:
        pass
    # Fallback to local SQLite
    from finagent.gateway.state_store import is_token_revoked as local_check
    return local_check(jti)


# ── Subscription / plan helpers ───────────────────────────────────────────

def _week_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


async def get_user_plan(email: str) -> str:
    """Return the user's subscription plan (defaults to 'free')."""
    profile = await get_user_by_email(email)
    if profile and profile.get("plan"):
        return str(profile.get("plan")).strip().lower()
    return "free"


async def update_user_plan(email: str, plan: str) -> bool:
    """Update the user's plan in the profiles table."""
    url = f"{_get_supabase_url()}/rest/v1/profiles"
    params = {"email": f"eq.{email}"}
    payload = {"plan": plan.lower().strip()}
    headers = get_headers()
    headers["Prefer"] = "return=minimal"
    try:
        async with _supabase_async_client() as client:
            res = await client.patch(url, params=params, json=payload, headers=headers)
            return res.is_success
    except Exception as exc:
        logger.warning("Failed to update plan for %s: %s", email, exc)
        return False


async def get_deep_runs_used(email: str) -> tuple[int, datetime]:
    """Return (used_count, period_start) for the user's deep-run weekly quota."""
    profile = await get_user_by_email(email)
    if not profile:
        return 0, _week_start_utc()
    used = int(profile.get("deep_runs_used") or 0)
    period_start = profile.get("deep_runs_period_start")
    if period_start:
        try:
            if isinstance(period_start, str):
                period_start = datetime.fromisoformat(period_start.replace("Z", "+00:00"))
        except Exception:
            period_start = _week_start_utc()
    else:
        period_start = _week_start_utc()
    return used, period_start


async def increment_deep_runs_used(email: str) -> tuple[int, datetime]:
    """Increment the user's weekly deep-run count. Resets the counter if the week has changed.

    Returns the new (used_count, period_start).
    """
    profile = await get_user_by_email(email)
    if not profile:
        return 0, _week_start_utc()

    used = int(profile.get("deep_runs_used") or 0)
    period_start = profile.get("deep_runs_period_start")
    if period_start:
        try:
            if isinstance(period_start, str):
                period_start = datetime.fromisoformat(period_start.replace("Z", "+00:00"))
        except Exception:
            period_start = _week_start_utc()
    else:
        period_start = _week_start_utc()

    current_week_start = _week_start_utc()
    if period_start < current_week_start:
        used = 0
        period_start = current_week_start

    used += 1

    url = f"{_get_supabase_url()}/rest/v1/profiles"
    params = {"email": f"eq.{email}"}
    payload = {
        "deep_runs_used": used,
        "deep_runs_period_start": period_start.isoformat(),
    }
    headers = get_headers()
    headers["Prefer"] = "return=minimal"
    try:
        async with _supabase_async_client() as client:
            res = await client.patch(url, params=params, json=payload, headers=headers)
            if not res.is_success:
                logger.warning("Failed to update deep_runs_used for %s: %s", email, res.text)
    except Exception as exc:
        logger.warning("Failed to update deep_runs_used for %s: %s", email, exc)

    return used, period_start


async def record_payment(
    user_id: str,
    razorpay_order_id: str,
    amount: int,
    currency: str = "INR",
    status: str = "created",
) -> dict | None:
    """Insert a new payment record for a Razorpay order."""
    url = f"{_get_supabase_url()}/rest/v1/payments"
    payload = {
        "user_id": user_id,
        "razorpay_order_id": razorpay_order_id,
        "amount": amount,
        "currency": currency,
        "status": status,
    }
    headers = get_headers()
    headers["Prefer"] = "return=representation"
    try:
        async with _supabase_async_client() as client:
            res = await client.post(url, json=payload, headers=headers)
            if res.is_success:
                data = res.json()
                return data[0] if isinstance(data, list) and data else data
    except Exception as exc:
        logger.warning("Failed to record payment for order %s: %s", razorpay_order_id, exc)
    return None


async def get_payment_by_order_id(razorpay_order_id: str) -> dict | None:
    """Fetch a payment record by Razorpay order id."""
    url = f"{_get_supabase_url()}/rest/v1/payments"
    params = {
        "razorpay_order_id": f"eq.{razorpay_order_id}",
        "select": "*",
    }
    try:
        async with _supabase_async_client() as client:
            res = await client.get(url, params=params, headers=get_headers())
            if res.is_success:
                data = res.json()
                if data and len(data) > 0:
                    return data[0]
    except Exception as exc:
        logger.warning("Failed to fetch payment for order %s: %s", razorpay_order_id, exc)
    return None


async def update_payment_verified(
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> bool:
    """Mark a payment as verified/paid."""
    url = f"{_get_supabase_url()}/rest/v1/payments"
    params = {"razorpay_order_id": f"eq.{razorpay_order_id}"}
    payload = {
        "razorpay_payment_id": razorpay_payment_id,
        "razorpay_signature": razorpay_signature,
        "status": "paid",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    headers = get_headers()
    headers["Prefer"] = "return=minimal"
    try:
        async with _supabase_async_client() as client:
            res = await client.patch(url, params=params, json=payload, headers=headers)
            return res.is_success
    except Exception as exc:
        logger.warning("Failed to verify payment for order %s: %s", razorpay_order_id, exc)
        return False


