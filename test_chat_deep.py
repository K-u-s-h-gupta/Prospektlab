"""Test deep mode chat with Reliance query."""
import json
import pathlib
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

BASE = "http://127.0.0.1:8000"

payload = json.dumps({
    "message": "Deep analysis of Reliance Industries - governance risks, promoter pledge exposure, regulatory actions, and financial health",
    "mode": "deep",
    "user_email": "ar2108925@gmail.com",
}).encode()

req = urllib.request.Request(
    f"{BASE}/chat/research",
    data=payload,
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    },
)

print("Starting deep mode research...")
t0 = time.time()
try:
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read())
    sid = data.get("session_id", "")
    print(f"Session: {sid}")
    print(f"Mode: {data.get('mode', 'N/A')}")
except Exception as e:
    print(f"Failed to start: {e}")
    exit(1)

# Poll for completion
print(f"\nPolling session {sid}...")
max_polls = 60
for i in range(max_polls):
    try:
        req = urllib.request.Request(
            f"{BASE}/sessions/{sid}/events?limit=500",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = urllib.request.urlopen(req, timeout=10)
        events_data = json.loads(resp.read())
        events = events_data.get("events", [])
        event_types = [e.get("type") for e in events]

        elapsed = time.time() - t0
        phases = [e.get("note", e.get("phase", "?")) for e in events if e.get("type") == "phase"]
        last_phase = phases[-1] if phases else "starting"
        print(f"  [{i+1}] {elapsed:.0f}s | events={len(events)} | phase={last_phase}")

        if "final" in event_types:
            print(f"\n  COMPLETED in {elapsed:.1f}s!")
            break
        if "error" in event_types:
            err = [e for e in events if e.get("type") == "error"]
            print(f"\n  ERROR: {err[-1].get('message', '?')}")
            break
    except Exception as e:
        print(f"  [{i+1}] poll error: {e}")

    time.sleep(5)

# Read memo
memo_path = pathlib.Path(f"D:\\PROSPEKTLAB\\.finagent\\memos\\{sid}.md")
if memo_path.is_file():
    memo = memo_path.read_text(encoding="utf-8")
    print(f"\n--- DEEP MODE MEMO ({len(memo)} chars) ---")
    print(memo[:4000])
    if len(memo) > 4000:
        print(f"\n... ({len(memo) - 4000} more chars)")
else:
    print(f"\nMemo file not found at {memo_path}")

# Event summary
print(f"\n--- EVENT SUMMARY ---")
req = urllib.request.Request(
    f"{BASE}/sessions/{sid}/events?limit=500",
    headers={"Authorization": f"Bearer {token}"},
)
resp = urllib.request.urlopen(req, timeout=10)
events_data = json.loads(resp.read())
events = events_data.get("events", [])
for e in events:
    etype = e.get("type", "?")
    detail = ""
    if etype == "phase":
        detail = f" -> {e.get('note', e.get('phase', '?'))[:80]}"
    elif etype == "ikg_grounded":
        detail = f" -> confidence={e.get('confidence')}, coverage={json.dumps(e.get('coverage', {}))[:80]}"
    elif etype == "agent_task":
        detail = f" -> {e.get('task', '?')}: {e.get('note', '?')[:60]}"
    elif etype == "final":
        detail = f" -> elapsed={e.get('elapsed_ms')}ms, quality={e.get('quality_score')}, citations={e.get('citations')}"
    elif etype in ("memo_token", "memo"):
        detail = f" -> {e.get('chars', '?')} chars"
    print(f"  {etype}{detail}")
