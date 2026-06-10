"""Test standard mode chat with Reliance query."""
import json
import time
import datetime as dt
import urllib.request

import jwt

SECRET = "OWddno9duGBrz6Midii4rEaq4pL43QSB6G8s13b6kazQgAwigiiYe7HGzXKVmtGj"
now = dt.datetime.now(dt.timezone.utc)
token = jwt.encode(
    {
        "sub": "test-user-1",
        "email": "ar2108925@gmail.com",
        "iat": now,
        "exp": now + dt.timedelta(hours=1),
        "iss": "prospektlab",
        "aud": "prospektlab-api",
    },
    SECRET,
    algorithm="HS256",
)

payload = json.dumps({
    "message": "Give me a comprehensive overview of Reliance Industries including governance, ownership structure, and any regulatory risks",
    "mode": "standard",
    "user_email": "ar2108925@gmail.com",
}).encode()

req = urllib.request.Request(
    "http://127.0.0.1:8000/chat/research",
    data=payload,
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    },
)

print("Sending standard mode request...")
t0 = time.time()
try:
    resp = urllib.request.urlopen(req, timeout=120)
    data = json.loads(resp.read())
    elapsed = time.time() - t0
    print(f"Status: {resp.status}")
    print(f"Elapsed: {elapsed:.1f}s")
    print(f"Session: {data.get('session_id', 'N/A')}")
    print(f"Keys: {list(data.keys())}")

    if "memo" in data:
        memo = data["memo"]
        print(f"Memo length: {len(memo)} chars")
        print(f"\n--- MEMO ---")
        print(memo[:2000])
        if len(memo) > 2000:
            print(f"\n... ({len(memo) - 2000} more chars)")
    elif "error" in data:
        print(f"Error: {data['error']}")
    else:
        print(json.dumps(data, indent=2, default=str)[:2000])

    # Test session status endpoint (was crashing with datetime serialization)
    sid = data.get("session_id")
    if sid:
        print(f"\n--- Testing /sessions/{sid}/status ---")
        req2 = urllib.request.Request(
            f"http://127.0.0.1:8000/sessions/{sid}/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp2 = urllib.request.urlopen(req2, timeout=10)
        status_data = json.loads(resp2.read())
        print(f"Status endpoint: {resp2.status} OK")
        print(f"Session state: {status_data.get('state', 'N/A')}")

        print(f"\n--- Testing /sessions/{sid}/events ---")
        req3 = urllib.request.Request(
            f"http://127.0.0.1:8000/sessions/{sid}/events",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp3 = urllib.request.urlopen(req3, timeout=10)
        events_data = json.loads(resp3.read())
        print(f"Events endpoint: {resp3.status} OK")
        print(f"Event count: {len(events_data.get('events', []))}")
        event_types = {}
        for e in events_data.get("events", []):
            t = e.get("type", "unknown")
            event_types[t] = event_types.get(t, 0) + 1
        print(f"Event types: {event_types}")

except Exception as e:
    elapsed = time.time() - t0
    print(f"FAILED after {elapsed:.1f}s: {e}")
    import traceback
    traceback.print_exc()
