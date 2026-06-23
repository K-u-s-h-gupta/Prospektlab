#!/usr/bin/env python
"""Generate a fresh Upstox access token via headless TOTP login and write it to
`.upstox/access_token.txt`, where the gateway's market feed reads it.

Run this once daily, shortly after the 03:30 IST token expiry and before market
open (e.g. 06:00 IST) — schedule it with Windows Task Scheduler / cron. The feed
re-reads the token on every reconnect, so a refreshed token is picked up without
restarting the gateway.

SECURITY — read this:
  This logs in with your FULL Upstox credentials + TOTP seed, which must live in
  `backend/finagent/.env` (gitignored). Storing the TOTP secret beside the
  password defeats 2FA: anyone who can read that file controls your account
  (including placing orders). Keep the file local, never commit it, lock its
  permissions, and prefer a low-funds / data-only account if possible.

Required in backend/finagent/.env (or environment):
  UPSTOX_USERNAME       10-digit mobile number
  UPSTOX_PASSWORD       account password
  UPSTOX_PIN_CODE       6-digit PIN
  UPSTOX_TOTP_SECRET    TOTP secret seed (enable TOTP in Upstox first)
  UPSTOX_CLIENT_ID      API key from your Upstox app
  UPSTOX_CLIENT_SECRET  API secret from your Upstox app
  UPSTOX_REDIRECT_URI   OAuth redirect URI configured on the app

Usage:
  pip install upstox-totp --ignore-requires-python
  python scripts/upstox_token.py
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for candidate in (ROOT / "backend" / "finagent" / ".env", ROOT / ".env"):
        if candidate.exists():
            load_dotenv(candidate)


def token_file_path() -> Path:
    """Returns the path where the access token is stored on disk."""
    token_dir = ROOT / ".upstox"
    token_dir.mkdir(exist_ok=True)
    return token_dir / "access_token.txt"


def main() -> int:
    _load_env()
    try:
        from upstox_totp import UpstoxTOTP
    except ImportError:
        print("upstox-totp not installed - run: pip install upstox-totp --ignore-requires-python", file=sys.stderr)
        return 2

    try:
        upx = UpstoxTOTP()
        resp = upx.app_token.get_access_token()
    except Exception as exc:  # noqa: BLE001
        print(f"token generation failed: {exc}", file=sys.stderr)
        return 1

    if not getattr(resp, "success", False) or not getattr(resp, "data", None):
        print("token generation unsuccessful (check credentials / TOTP secret)", file=sys.stderr)
        return 1

    token = resp.data.access_token
    if not token:
        print("empty access token returned", file=sys.stderr)
        return 1

    path = token_file_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(token, encoding="utf-8")
    try:  # best-effort 0600 (POSIX; no-op on Windows)
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass
    tmp.replace(path)
    
    # Also write back to .env
    env_path = ROOT / "backend" / "finagent" / ".env"
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
        updated = False
        new_lines = []
        for line in lines:
            if line.startswith("UPSTOX_ACCESS_TOKEN="):
                new_lines.append(f"UPSTOX_ACCESS_TOKEN={token}")
                updated = True
            else:
                new_lines.append(line)
        if not updated:
            new_lines.append(f"UPSTOX_ACCESS_TOKEN={token}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # Never print the token itself.
    print(f"✅ Upstox token written to {path} and .env ({len(token)} chars). Feed will pick it up on next reconnect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
