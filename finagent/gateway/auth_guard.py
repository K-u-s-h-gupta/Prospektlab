from __future__ import annotations

import os
from typing import Any

import jwt
from fastapi import HTTPException


def decode_current_user_token(actual_token: str | None, *, local_jwt_secret: str) -> dict[str, Any]:
    """Validate local or Supabase HS256 JWTs without external network calls."""

    if not actual_token:
        raise HTTPException(status_code=401, detail="Missing or invalid authentication credentials")

    try:
        payload = jwt.decode(actual_token, local_jwt_secret, algorithms=["HS256"])
        user_id = payload.get("user_id") or payload.get("sub")
        email = payload.get("email")
        if not user_id or not email:
            raise HTTPException(status_code=401, detail="Invalid token details")
        return {
            "user_id": user_id,
            "tenant_id": user_id,
            "email": email,
            "auth_provider": "local_jwt",
        }
    except HTTPException:
        raise
    except Exception as local_exc:
        if actual_token.count(".") != 2:
            raise HTTPException(status_code=401, detail="Could not validate authentication credentials") from local_exc

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
        )
        user_id = payload.get("sub") or payload.get("user_id")
        email = payload.get("email")
        if not user_id or not email:
            raise HTTPException(status_code=401, detail="Invalid token details")
        return {
            "user_id": user_id,
            "tenant_id": user_id,
            "email": email,
            "auth_provider": "supabase_jwt",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Could not validate authentication credentials") from exc
