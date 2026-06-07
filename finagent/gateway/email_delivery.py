from __future__ import annotations

import logging
import os
import smtplib
from dataclasses import dataclass
from email.mime.text import MIMEText


logger = logging.getLogger("finagent.gateway.email_delivery")


@dataclass(slots=True)
class EmailDeliveryOutcome:
    delivered: bool
    provider: str
    detail: str = ""


def _acs_connection_string() -> str:
    return (
        os.getenv("ACS_EMAIL_CONNECTION_STRING", "").strip()
        or os.getenv("AZURE_COMMUNICATION_CONNECTION_STRING", "").strip()
    )


def _acs_sender_address() -> str:
    explicit = os.getenv("ACS_EMAIL_FROM", "").strip()
    if explicit:
        return explicit

    username = os.getenv("ACS_EMAIL_SENDER_USERNAME", "").strip()
    domain = os.getenv("ACS_EMAIL_DOMAIN", "").strip()
    if username and domain:
        return f"{username}@{domain}"
    return ""


def _send_via_acs(
    *,
    to_email: str,
    subject: str,
    plain_text: str,
    html: str | None = None,
) -> EmailDeliveryOutcome:
    connection_string = _acs_connection_string()
    sender = _acs_sender_address()
    if not connection_string or not sender:
        return EmailDeliveryOutcome(
            delivered=False,
            provider="acs",
            detail="ACS email is not fully configured.",
        )

    try:
        from azure.communication.email import EmailClient
    except ImportError:
        logger.warning("ACS email requested but azure-communication-email is not installed.")
        return EmailDeliveryOutcome(
            delivered=False,
            provider="acs",
            detail="azure-communication-email is not installed.",
        )

    message = {
        "senderAddress": sender,
        "recipients": {"to": [{"address": to_email}]},
        "content": {
            "subject": subject,
            "plainText": plain_text,
        },
    }
    if html:
        message["content"]["html"] = html

    try:
        client = EmailClient.from_connection_string(connection_string)
        poller = client.begin_send(message)
        result = poller.result()
        message_id = ""
        if isinstance(result, dict):
            message_id = str(result.get("id") or result.get("messageId") or "")
        else:
            message_id = str(
                getattr(result, "id", "")
                or getattr(result, "message_id", "")
                or getattr(result, "messageId", "")
            )
        return EmailDeliveryOutcome(
            delivered=True,
            provider="acs",
            detail=message_id,
        )
    except Exception as exc:
        logger.warning("ACS email send failed for %s: %s", to_email, exc)
        return EmailDeliveryOutcome(
            delivered=False,
            provider="acs",
            detail=str(exc),
        )


def _send_via_smtp(
    *,
    to_email: str,
    subject: str,
    plain_text: str,
) -> EmailDeliveryOutcome:
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = os.getenv("SMTP_PORT", "").strip()
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "no-reply@prospektlab.com").strip()

    if not smtp_host or not smtp_user or not smtp_password:
        return EmailDeliveryOutcome(
            delivered=False,
            provider="smtp",
            detail="SMTP email is not fully configured.",
        )

    try:
        msg = MIMEText(plain_text)
        msg["Subject"] = subject
        msg["From"] = smtp_from
        msg["To"] = to_email

        port = int(smtp_port) if smtp_port else 587
        server = smtplib.SMTP(smtp_host, port, timeout=10)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_from, [to_email], msg.as_string())
        server.quit()
        return EmailDeliveryOutcome(delivered=True, provider="smtp")
    except Exception as exc:
        logger.warning("SMTP email send failed for %s: %s", to_email, exc)
        return EmailDeliveryOutcome(
            delivered=False,
            provider="smtp",
            detail=str(exc),
        )


def send_email_message(
    *,
    to_email: str,
    subject: str,
    plain_text: str,
    html: str | None = None,
) -> EmailDeliveryOutcome:
    acs_outcome = _send_via_acs(
        to_email=to_email,
        subject=subject,
        plain_text=plain_text,
        html=html,
    )
    if acs_outcome.delivered:
        return acs_outcome

    smtp_outcome = _send_via_smtp(
        to_email=to_email,
        subject=subject,
        plain_text=plain_text,
    )
    if smtp_outcome.delivered:
        return smtp_outcome

    detail = acs_outcome.detail or smtp_outcome.detail or "Email delivery is not configured."
    return EmailDeliveryOutcome(delivered=False, provider="none", detail=detail)
