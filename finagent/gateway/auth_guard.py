from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any

import jwt
from fastapi import HTTPException


def decode_current_user_token(actual_token: str | None, *, local_jwt_secret: str) -> dict[str, Any]:
    """Validate local or Supabase HS256 JWTs with exp/iat/iss/aud enforcement and revocation checks.

    Hardening changes:
    - Requires 'iss' and 'aud' claims for local tokens.
    - Rejects tokens with algorithm != HS256.
    - Validates local issuer == 'prospektlab' and audience == 'prospektlab-api'.
    - Rejects tokens with missing or blank user_id/email.
    """

    if not actual_token:
        raise HTTPException(status_code=401, detail="Missing or invalid authentication credentials")

    try:
        payload = jwt.decode(
            actual_token,
            local_jwt_secret,
            algorithms=["HS256"],
            audience="prospektlab-api",
            options={"require": ["exp", "iat"]},
            leeway=60,  # 60-second clock skew tolerance
        )
        # Issuer / audience validation for local tokens
        iss = payload.get("iss")
        aud = payload.get("aud")
        if iss != "prospektlab":
            raise HTTPException(status_code=401, detail="Invalid token issuer")
        if aud != "prospektlab-api":
            raise HTTPException(status_code=401, detail="Invalid token audience")

        # Revocation check
        jti = payload.get("jti")
        if jti:
            from finagent.gateway.state_store import is_token_revoked
            if is_token_revoked(jti):
                raise HTTPException(status_code=401, detail="Token has been revoked")

        user_id = payload.get("user_id") or payload.get("sub")
        email = payload.get("email")
        name = payload.get("name") or email
        if not user_id or not email:
            raise HTTPException(status_code=401, detail="Invalid token details")
        return {
            "user_id": user_id,
            "tenant_id": user_id,
            "email": email,
            "name": name,
            "auth_provider": "local_jwt",
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except HTTPException:
        raise
    except Exception:
        # Token doesn't match local secret or is malformed — try Supabase
        pass

    supabase_jwt_secret = os.getenv("SUPABASE_JWT_SECRET")
    if not supabase_jwt_secret:
        raise HTTPException(
            status_code=401,
            detail="Supabase JWT verification secret is required",
        )

    try:
        payload = jwt.decode(
            actual_token,
            supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
            options={"require": ["exp", "iat"]},
            leeway=60,
        )
        # Revocation check (also applies to Supabase tokens if we track them)
        jti = payload.get("jti")
        if jti:
            from finagent.gateway.state_store import is_token_revoked
            if is_token_revoked(jti):
                raise HTTPException(status_code=401, detail="Token has been revoked")

        user_id = payload.get("sub") or payload.get("user_id")
        email = payload.get("email")
        name = payload.get("name") or email
        if not user_id or not email:
            raise HTTPException(status_code=401, detail="Invalid token details")
        return {
            "user_id": user_id,
            "tenant_id": user_id,
            "email": email,
            "name": name,
            "auth_provider": "supabase_jwt",
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Could not validate authentication credentials") from exc
