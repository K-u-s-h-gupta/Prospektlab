import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jwt
from dotenv import load_dotenv


load_dotenv("finagent/.env", override=True)
load_dotenv(".env", override=True)


def _auth_headers() -> dict[str, str]:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET is required for chat smoke tests")
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "user_id": "local-chat-smoke",
            "email": "local-chat-smoke@example.com",
            "name": "Local Chat Smoke",
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(hours=2),
            "iss": "prospektlab",
            "aud": "prospektlab-api",
        },
        secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}

async def main():
    async with httpx.AsyncClient(timeout=300) as client:
        headers = _auth_headers()
        try:
            resp = await client.post(
                'http://localhost:8000/chat/research',
                json={
                    'message': 'Who owns Adani Enterprises through which entities?',
                    'mode': 'standard',
                    'max_wall_seconds': 90,
                },
                headers=headers,
            )
            print("POST Status:", resp.status_code)
            print("POST Response:", resp.text)
            
            data = resp.json()
            session_id = data.get('session_id')
            if not session_id:
                return
            
            # Now stream events
            async with client.stream('GET', f"http://localhost:8000/sessions/{session_id}/stream", headers=headers) as stream:
                async for chunk in stream.aiter_text():
                    print("SSE:", chunk)
        except Exception as e:
            print("Error:", e)

asyncio.run(main())
