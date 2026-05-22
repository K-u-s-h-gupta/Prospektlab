import urllib.request
import json
import jwt
import time
import sys

# Reconfigure stdout/stderr to UTF-8 to prevent charmap codec errors on Windows
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    pass

def main():
    token = jwt.encode({"user_id": "test-user", "email": "test@example.com"}, "super_secret_ipo_key_123", algorithm="HS256")
    
    url = "http://127.0.0.1:8080/research/start"
    data = {
        "target": 'Reliance Industries "annual report" site:nseindia.com',
        "objective": "test query operators",
        "mode": "chat",
        "max_steps": 4,
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req) as res:
            resp_data = json.loads(res.read().decode("utf-8"))
            print("Start response:", resp_data)
            sid = resp_data["session_id"]
    except Exception as e:
        print("Failed to start research:", e)
        if hasattr(e, "read"):
            print(e.read().decode("utf-8"))
        return
        
    print(f"Polling events for session {sid}...")
    events_url = f"http://127.0.0.1:8080/sessions/{sid}/events?limit=100"
    
    last_after = 0
    for _ in range(30):
        time.sleep(2)
        poll_url = f"{events_url}&after={last_after}"
        poll_req = urllib.request.Request(
            poll_url,
            headers={"Authorization": f"Bearer {token}"}
        )
        try:
            with urllib.request.urlopen(poll_req) as res:
                poll_data = json.loads(res.read().decode("utf-8"))
                events = poll_data.get("events", [])
                for ev in events:
                    print(f"Event: {ev.get('type')} - {ev.get('message') or ev.get('note') or ev.get('phase')}")
                    if ev.get("type") == "error":
                        print("CRASH DETECTED:", ev)
                        return
                    if ev.get("type") == "final":
                        print("Completed successfully!")
                        return
                last_after = poll_data.get("next_after", last_after)
                if poll_data.get("closed"):
                    print("Session closed.")
                    return
        except Exception as e:
            print("Polling failed:", e)

if __name__ == "__main__":
    main()
