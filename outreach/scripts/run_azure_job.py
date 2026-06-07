from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


DEFAULT_SENDERS = [
    {
        "key": "aryan",
        "name": "Aryan",
        "email": "aryan@notify.prospektlab.com",
        "reply_to": "aryan@prospektlab.com",
    },
    {
        "key": "kushargra",
        "name": "Kushargra",
        "email": "kushargra@notify.prospektlab.com",
        "reply_to": "kushargra@prospektlab.com",
    },
    {
        "key": "riya",
        "name": "Riya",
        "email": "riya@notify.prospektlab.com",
        "reply_to": "aryan@prospektlab.com",
    },
    {
        "key": "ananya",
        "name": "Ananya",
        "email": "ananya@notify.prospektlab.com",
        "reply_to": "kushargra@prospektlab.com",
    },
    {
        "key": "rohan",
        "name": "Rohan",
        "email": "rohan@notify.prospektlab.com",
        "reply_to": "aryan@prospektlab.com",
    },
    {
        "key": "aditya",
        "name": "Aditya",
        "email": "aditya@notify.prospektlab.com",
        "reply_to": "kushargra@prospektlab.com",
    },
    {
        "key": "neha",
        "name": "Neha",
        "email": "neha@notify.prospektlab.com",
        "reply_to": "aryan@prospektlab.com",
    },
    {
        "key": "ishaan",
        "name": "Ishaan",
        "email": "ishaan@notify.prospektlab.com",
        "reply_to": "kushargra@prospektlab.com",
    },
    {
        "key": "kavya",
        "name": "Kavya",
        "email": "kavya@notify.prospektlab.com",
        "reply_to": "aryan@prospektlab.com",
    },
]


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def _maybe_json_env(name: str) -> list[dict[str, str]] | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise SystemExit(f"{name} must be a JSON array of sender objects.")
    senders: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise SystemExit(f"{name} must contain objects only.")
        senders.append(
            {
                "key": str(item.get("key", "")).strip().lower(),
                "name": str(item.get("name", "")).strip(),
                "email": str(item.get("email", "")).strip().lower(),
                "reply_to": str(item.get("reply_to", "")).strip().lower(),
            }
        )
    return senders


def build_config() -> dict[str, object]:
    senders = _maybe_json_env("OUTREACH_SENDERS_JSON") or DEFAULT_SENDERS
    return {
        "azure": {
            "connection_string": _required("ACS_EMAIL_CONNECTION_STRING"),
            "domain": os.getenv("OUTREACH_ACS_DOMAIN", "notify.prospektlab.com").strip(),
            "require_custom_domain": True,
            "allow_managed_domain": False,
            "verified": True,
        },
        "campaign": {
            "signup_url": os.getenv("OUTREACH_SIGNUP_URL", "https://prospektlab.com/signup").strip(),
            "whatsapp_group_url": os.getenv(
                "OUTREACH_WHATSAPP_GROUP_URL",
                "https://chat.whatsapp.com/Bpo5Bt5tVveGYGEVawkcUu",
            ).strip(),
            "unsubscribe_url": os.getenv(
                "OUTREACH_UNSUBSCRIBE_URL",
                "https://prospektlab.com/unsubscribe",
            ).strip(),
            "physical_address": _required("OUTREACH_PHYSICAL_ADDRESS"),
        },
        "suppression_sync": {
            "supabase_url": _required("OUTREACH_SUPABASE_URL"),
            "supabase_key": _required("OUTREACH_SUPABASE_KEY"),
        },
        "senders": senders,
    }


def main() -> int:
    repo_root = Path("/app")
    batch_script = repo_root / "outreach" / "scripts" / "run_supabase_outreach_batch.py"
    if not batch_script.exists():
        raise SystemExit(f"Batch script not found: {batch_script}")

    config = build_config()
    config_path = Path(os.getenv("OUTREACH_CONFIG_PATH", tempfile.gettempdir())) / "outreach.config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    command = [
        sys.executable,
        str(batch_script),
        "--config",
        str(config_path),
        "--owner-email",
        os.getenv("OUTREACH_OWNER_EMAIL", "aryan@prospektlab.com").strip(),
        "--campaign-name",
        os.getenv("OUTREACH_CAMPAIGN_NAME", "IndiaFinanceOutreach").strip(),
        "--max-send",
        os.getenv("OUTREACH_MAX_SEND", "30").strip(),
        "--delay-seconds",
        os.getenv("OUTREACH_DELAY_SECONDS", "8").strip(),
        "--min-email-confidence",
        os.getenv("OUTREACH_MIN_EMAIL_CONFIDENCE", "0.85").strip(),
    ]
    if _truthy(os.getenv("OUTREACH_ALLOW_SHARED_INBOXES")):
        command.append("--allow-shared-inboxes")
    if _truthy(os.getenv("OUTREACH_SEND", "true")):
        command.append("--send")

    print("Azure outreach runner starting with config:", config_path)
    print("Executing:", " ".join(command))
    completed = subprocess.run(command, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
