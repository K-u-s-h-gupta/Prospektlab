from __future__ import annotations

import argparse
import csv
import html
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PLACEHOLDER_RE = re.compile(r"\b(todo|tbd|placeholder|example\.com|lorem|generic)\b", re.IGNORECASE)


@dataclass(slots=True)
class Sender:
    key: str
    name: str
    email: str
    reply_to: str


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return data


def load_template(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or not lines[0].lower().startswith("subject:"):
        raise ValueError("Template must start with `Subject: ...`.")
    subject = lines[0].split(":", 1)[1].strip()
    body = "\n".join(lines[1:]).strip()
    return subject, body


def render(text: str, values: dict[str, str]) -> str:
    rendered = text
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    missing = sorted(set(re.findall(r"{{\s*([a-zA-Z0-9_]+)\s*}}", rendered)))
    if missing:
        raise ValueError(f"Missing template values: {', '.join(missing)}")
    return rendered


def text_to_html(text: str) -> str:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    return "\n".join(f"<p>{html.escape(p).replace(chr(10), '<br/>')}</p>" for p in paragraphs)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def read_suppression(path: Path) -> set[str]:
    if not path.exists():
        return set()
    rows = read_csv_rows(path)
    return {row.get("email", "").lower() for row in rows if row.get("email")}


def append_sent_log(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    fields = ["sent_at", "email", "sender", "subject", "message_id", "source_url"]
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in fields})


def load_env_file_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for path in (Path("finagent/.env"), Path(".env")):
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in values:
                values[key] = value
    return values


def resolve_setting(config: dict[str, Any], env_values: dict[str, str], *names: str) -> str:
    for name in names:
        env_value = os.environ.get(name) or env_values.get(name)
        if env_value:
            return str(env_value).strip()
    current: Any = config
    for name in names[:1]:
        if "." not in name:
            continue
        value = config
        found = True
        for part in name.split("."):
            if not isinstance(value, dict) or part not in value:
                found = False
                break
            value = value[part]
        if found and str(value).strip():
            return str(value).strip()
    return ""


def sync_suppression_from_supabase(path: Path, config: dict[str, Any]) -> bool:
    sync_config = config.get("suppression_sync", {})
    env_values = load_env_file_values()
    supabase_url = (
        str(sync_config.get("supabase_url", "")).strip()
        or resolve_setting(config, env_values, "OUTREACH_SUPABASE_URL", "SUPABASE_URL")
    )
    supabase_key = (
        str(sync_config.get("supabase_key", "")).strip()
        or resolve_setting(config, env_values, "OUTREACH_SUPABASE_KEY", "SUPABASE_KEY")
    )
    if not supabase_url or not supabase_key:
        return False

    endpoint = (
        supabase_url.rstrip("/")
        + "/rest/v1/outreach_unsubscribes?select=email&order=updated_at.desc,email.asc"
    )
    req = urllib.request.Request(
        endpoint,
        headers={
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Accept": "application/json",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Unexpected suppression payload from Supabase.")

    remote_emails = {
        str(item.get("email", "")).strip().lower()
        for item in payload
        if isinstance(item, dict) and str(item.get("email", "")).strip()
    }
    combined = sorted(read_suppression(path) | remote_emails)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["email"])
        writer.writeheader()
        for email_addr in combined:
            writer.writerow({"email": email_addr})
    print(f"SYNC suppression: {len(remote_emails)} remote emails -> {path}")
    return True


def senders_from_config(config: dict[str, Any]) -> dict[str, Sender]:
    senders: dict[str, Sender] = {}
    for raw in config.get("senders", []):
        sender = Sender(
            key=str(raw.get("key", "")).strip().lower(),
            name=str(raw.get("name", "")).strip(),
            email=str(raw.get("email", "")).strip().lower(),
            reply_to=str(raw.get("reply_to", "")).strip().lower(),
        )
        if sender.key and sender.email:
            senders[sender.key] = sender
    if not senders:
        raise ValueError("At least one sender is required in config.")
    return senders


def validate_config(config: dict[str, Any], *, sending: bool, allow_managed_domain: bool) -> list[str]:
    issues: list[str] = []
    azure = config.get("azure", {})
    campaign = config.get("campaign", {})
    domain = str(azure.get("domain", "")).strip().lower()
    require_custom_domain = bool(azure.get("require_custom_domain", True))
    allow_managed_domain = allow_managed_domain or bool(azure.get("allow_managed_domain", False))

    if sending and not str(azure.get("connection_string", "")).strip():
        issues.append("azure.connection_string is required for live sends.")
    if sending and require_custom_domain and not allow_managed_domain and azure.get("verified") is not True:
        issues.append(f"{domain or 'custom domain'} is not marked verified in config. Re-run setup after DNS verification.")
    if sending and require_custom_domain and not allow_managed_domain:
        for raw in config.get("senders", []):
            sender_email = str(raw.get("email", "")).strip().lower()
            if not domain or not sender_email.endswith("@" + domain):
                issues.append(f"{sender_email} is not on the required branded domain {domain}.")
            if sender_email.endswith(".azurecomm.net"):
                issues.append(f"{sender_email} is an Azure-managed sender and should not be used for outreach.")
    if sending and not str(campaign.get("unsubscribe_url", "")).strip():
        issues.append("campaign.unsubscribe_url is required for live sends.")
    if sending and not str(campaign.get("physical_address", "")).strip():
        issues.append("campaign.physical_address is required for live sends.")
    return issues


def validate_lead(row: dict[str, str]) -> list[str]:
    issues: list[str] = []
    email_addr = row.get("email", "").lower()
    if not EMAIL_RE.match(email_addr):
        issues.append("invalid email")
    if len(row.get("first_name", "")) < 2:
        issues.append("missing first_name")
    if len(row.get("hook", "")) < 30:
        issues.append("hook is too thin")
    if len(row.get("compliment", "")) < 30:
        issues.append("compliment is too thin")
    combined = " ".join(row.get(k, "") for k in ("hook", "compliment", "subject"))
    if PLACEHOLDER_RE.search(combined):
        issues.append("contains placeholder/generic text")
    return issues


def _default_platform_intro(row: dict[str, str]) -> str:
    role = str(row.get("role", "")).strip()
    company = str(row.get("company", "")).strip()
    if role and company:
        return (
            "We are building ProspektLab as a research workspace that brings filings, news, portfolio context, "
            "and market data into one place so the work feels less scattered."
        )
    return (
        "We are building ProspektLab as a research workspace that brings filings, news, portfolio context, "
        "and market data into one place instead of across scattered tabs and notes."
    )


def _default_cta_line() -> str:
    return (
        "If you are open to it, I would love to get your honest reaction after a quick 10-minute look. "
        "Even a short reply on what feels useful, missing, or unnecessary would help us shape it."
    )


def build_message(
    *,
    row: dict[str, str],
    sender: Sender,
    config: dict[str, Any],
    template_subject: str,
    template_body: str,
) -> dict[str, str]:
    campaign = config.get("campaign", {})
    recipient_email = row.get("email", "").strip().lower()
    unsubscribe_base = str(campaign.get("unsubscribe_url", "")).strip()
    unsubscribe_url = unsubscribe_base
    if unsubscribe_base and recipient_email:
        parsed = urllib.parse.urlsplit(unsubscribe_base)
        params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not any(key.lower() == "email" for key, _ in params):
            params.append(("email", recipient_email))
        unsubscribe_url = urllib.parse.urlunsplit(
            parsed._replace(query=urllib.parse.urlencode(params))
        )

    if sender.key in {"aryan", "kushargra"}:
        intro_line = f"I am {sender.name}, one of the founders of ProspektLab."
    else:
        intro_line = f"I am {sender.name} from ProspektLab."
    signature_block = f"{sender.name}\nProspektLab"
    whatsapp_group_url = str(campaign.get("whatsapp_group_url", "")).strip()
    feedback_group_line = str(row.get("feedback_group_line", "")).strip()
    if not feedback_group_line and whatsapp_group_url:
        feedback_group_line = (
            "If you do sign up and want to stay close to the build, the optional feedback group is here: "
            f"{whatsapp_group_url}"
        )

    values = {
        "first_name": row.get("first_name") or "there",
        "company": row.get("company", ""),
        "role": row.get("role", ""),
        "hook": row.get("hook", ""),
        "compliment": row.get("compliment", ""),
        "subject": row.get("subject") or template_subject or "Would love your feedback on ProspektLab",
        "sender_name": sender.name,
        "intro_line": intro_line,
        "platform_intro": str(row.get("platform_intro", "")).strip() or _default_platform_intro(row),
        "cta_line": str(row.get("cta_line", "")).strip() or _default_cta_line(),
        "signature_block": signature_block,
        "signup_url": str(campaign.get("signup_url", "")).strip(),
        "whatsapp_group_url": whatsapp_group_url,
        "feedback_group_line": feedback_group_line,
        "unsubscribe_url": unsubscribe_url or "reply unsubscribe",
        "unsubscribe_link_line": "",
        "physical_address": str(campaign.get("physical_address", "")).strip(),
    }
    if unsubscribe_url:
        values["unsubscribe_link_line"] = f"Unsubscribe here: {values['unsubscribe_url']}"
    subject = render(values["subject"], values)
    text = render(template_body, values)
    return {"subject": subject, "text": text, "html": text_to_html(text)}


def send_acs_email(
    *,
    connection_string: str,
    sender: Sender,
    to_email: str,
    subject: str,
    text: str,
    html_body: str,
) -> str:
    from azure.communication.email import EmailClient
    from azure.communication.email._operations._operations import build_email_send_request
    from azure.core.exceptions import HttpResponseError

    message: dict[str, Any] = {
        "senderAddress": sender.email,
        "recipients": {"to": [{"address": to_email}]},
        "content": {
            "subject": subject,
            "plainText": text,
            "html": html_body,
        },
    }
    if sender.reply_to:
        message["replyTo"] = [{"address": sender.reply_to}]

    client = EmailClient.from_connection_string(connection_string)
    request = build_email_send_request(
        operation_id=None,
        content_type="application/json",
        api_version=client._config.api_version,  # type: ignore[attr-defined]
        json=message,
        content=None,
        headers={},
        params={},
    )
    request.url = client._client.format_url(  # type: ignore[attr-defined]
        request.url,
        endpoint=client._serialize.url(  # type: ignore[attr-defined]
            "self._config.endpoint",
            client._config.endpoint,  # type: ignore[attr-defined]
            "str",
            skip_quote=True,
        ),
    )
    pipeline_response = client._client._pipeline.run(  # type: ignore[attr-defined]
        request,
        stream=False,
        connection_timeout=10,
        read_timeout=20,
    )
    response = pipeline_response.http_response
    if response.status_code != 202:
        try:
            response.read()
        except Exception:
            pass
        raise HttpResponseError(response=response)

    payload = response.json() if response.content else {}
    if isinstance(payload, dict):
        return str(
            payload.get("id")
            or payload.get("messageId")
            or response.headers.get("Operation-Location")
            or payload.get("status")
            or ""
        )
    return str(response.headers.get("Operation-Location") or "")


def choose_sender(row: dict[str, str], senders: dict[str, Sender], index: int) -> Sender:
    requested = row.get("sender", "").strip().lower()
    if requested:
        if requested not in senders:
            raise ValueError(f"Unknown sender `{requested}` for {row.get('email')}.")
        return senders[requested]
    return list(senders.values())[index % len(senders)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Controlled ProspektLab ACS outreach sender.")
    parser.add_argument("--config", type=Path, default=Path("outreach/config.local.json"))
    parser.add_argument("--leads", type=Path, default=Path("outreach/leads.csv"))
    parser.add_argument("--template", type=Path, default=Path("outreach/templates/prospektlab_feedback.md"))
    parser.add_argument("--suppression", type=Path, default=Path("outreach/state/suppression.csv"))
    parser.add_argument("--sent-log", type=Path, default=Path("outreach/state/sent_log.csv"))
    parser.add_argument("--max-per-run", type=int, default=10)
    parser.add_argument("--delay-seconds", type=float, default=90.0)
    parser.add_argument("--send", action="store_true", help="Actually send email. Omit for dry run.")
    parser.add_argument("--allow-managed-domain", action="store_true", help="Override the branded-domain guard.")
    args = parser.parse_args()

    config = load_json(args.config)
    senders = senders_from_config(config)
    template_subject, template_body = load_template(args.template)
    config_issues = validate_config(config, sending=args.send, allow_managed_domain=args.allow_managed_domain)
    if config_issues:
        print("Configuration is not ready for live sending:")
        for issue in config_issues:
            print(f"- {issue}")
        return 2

    try:
        sync_suppression_from_supabase(args.suppression, config)
    except Exception as exc:
        print(f"WARN suppression sync skipped: {exc}")

    rows = read_csv_rows(args.leads)
    suppressed = read_suppression(args.suppression)
    sent = 0
    skipped = 0
    connection_string = str(config.get("azure", {}).get("connection_string", "")).strip()

    for index, row in enumerate(rows):
        if sent >= args.max_per_run:
            break

        email_addr = row.get("email", "").lower()
        if email_addr in suppressed:
            print(f"SKIP suppressed: {email_addr}")
            skipped += 1
            continue

        issues = validate_lead(row)
        if issues:
            print(f"SKIP quality: {email_addr or '(missing email)'} -> {', '.join(issues)}")
            skipped += 1
            continue

        try:
            sender = choose_sender(row, senders, index)
            message = build_message(
                row=row,
                sender=sender,
                config=config,
                template_subject=template_subject,
                template_body=template_body,
            )
        except Exception as exc:
            print(f"SKIP render: {email_addr} -> {exc}")
            skipped += 1
            continue

        if not args.send:
            print("")
            print(f"DRY RUN -> {email_addr}")
            print(f"From: {sender.name} <{sender.email}>")
            print(f"Reply-To: {sender.reply_to}")
            print(f"Subject: {message['subject']}")
            print(message["text"])
            sent += 1
            continue

        try:
            message_id = send_acs_email(
                connection_string=connection_string,
                sender=sender,
                to_email=email_addr,
                subject=message["subject"],
                text=message["text"],
                html_body=message["html"],
            )
            append_sent_log(args.sent_log, {
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "email": email_addr,
                "sender": sender.email,
                "subject": message["subject"],
                "message_id": message_id,
                "source_url": row.get("source_url", ""),
            })
            sent += 1
            print(f"SENT {sent}: {email_addr} via {sender.email} ({message_id or 'no message id'})")
            if sent < args.max_per_run:
                time.sleep(max(0.0, args.delay_seconds + random.uniform(-5.0, 5.0)))
        except Exception as exc:
            print(f"FAIL send: {email_addr} -> {exc}")
            skipped += 1

    mode = "sent" if args.send else "previewed"
    print("")
    print(f"Done: {sent} {mode}, {skipped} skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
