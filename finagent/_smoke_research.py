"""Smoke test for the gateway without a manual server.

Runs in-process: POST /research/start with a small step budget, then polls
`/sessions/{id}/events` until `final` or timeout.

Usage (from repo root):
    python -m finagent._smoke_research
"""

from __future__ import annotations

import sys
import time


def main() -> int:
    try:
        from starlette.testclient import TestClient
    except ImportError:
        print("starlette testclient missing — pip install fastapi", file=sys.stderr)
        return 1

    from finagent.gateway.run import app

    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post(
            "/research/start",
            json={
                "target": "RELIANCE",
                "objective": "smoke test run",
                "max_steps": 8,
                "max_wall_seconds": 180,
                "heartbeat_interval_s": 30,
            },
        )
        if r.status_code != 200:
            print("start failed", r.status_code, r.text, file=sys.stderr)
            return 1
        body = r.json()
        sid = body.get("session_id")
        if not sid:
            print("no session_id", body, file=sys.stderr)
            return 1
        print("session", sid)

        saw_source = False
        saw_final = False
        last_after = 0
        deadline = time.monotonic() + 150.0

        while time.monotonic() < deadline:
            ev = client.get("/sessions/{}/events".format(sid), params={"after": last_after, "limit": 200})
            if ev.status_code == 404:
                print("session vanished", file=sys.stderr)
                return 1
            data = ev.json()
            for e in data.get("events") or []:
                t = e.get("type")
                if t == "source":
                    saw_source = True
                if t == "final":
                    saw_final = True
                    print("final quality_score=", e.get("quality_score"), "steps=", e.get("steps"))
            last_after = data.get("next_after", last_after)
            if data.get("closed") and not saw_final:
                break
            if saw_final:
                break
            time.sleep(0.4)

        if not saw_final:
            print("timeout: no final event", file=sys.stderr)
            return 1
        if not saw_source:
            print("warning: no source event (search may be rate-limited)")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
