from __future__ import annotations

import logging
import os

from finagent.gateway.email_delivery import EmailDeliveryOutcome


logger = logging.getLogger("finagent.gateway.sms_delivery")


def _sms_connection_string() -> str:
    return (
        os.getenv("ACS_SMS_CONNECTION_STRING", "").strip()
        or os.getenv("ACS_EMAIL_CONNECTION_STRING", "").strip()
        or os.getenv("AZURE_COMMUNICATION_CONNECTION_STRING", "").strip()
    )


def _sms_sender() -> str:
    return os.getenv("ACS_SMS_FROM", "").strip()


def send_sms_message(*, to_phone: str, message: str) -> EmailDeliveryOutcome:
    connection_string = _sms_connection_string()
    sender = _sms_sender()
    if not connection_string or not sender:
        return EmailDeliveryOutcome(
            delivered=False,
            provider="sms",
            detail="ACS SMS is not fully configured.",
        )

    try:
        from azure.communication.sms import SmsClient
    except ImportError:
        logger.warning("ACS SMS requested but azure-communication-sms is not installed.")
        return EmailDeliveryOutcome(
            delivered=False,
            provider="sms",
            detail="azure-communication-sms is not installed.",
        )

    try:
        client = SmsClient.from_connection_string(connection_string)
        results = client.send(
            from_=sender,
            to=[to_phone],
            message=message,
            enable_delivery_report=True,
            tag="ProspektLabAuth",
        )
        if not results:
            return EmailDeliveryOutcome(
                delivered=False,
                provider="sms",
                detail="ACS SMS returned no result.",
            )

        result = results[0]
        successful = bool(getattr(result, "successful", False))
        detail = str(
            getattr(result, "message_id", "")
            or getattr(result, "http_status_code", "")
            or getattr(result, "to", "")
        )
        if successful:
            return EmailDeliveryOutcome(
                delivered=True,
                provider="sms",
                detail=detail,
            )

        error_message = str(getattr(result, "error_message", "") or detail or "Unknown SMS failure.")
        return EmailDeliveryOutcome(
            delivered=False,
            provider="sms",
            detail=error_message,
        )
    except Exception as exc:
        logger.warning("ACS SMS send failed for %s: %s", to_phone, exc)
        return EmailDeliveryOutcome(
            delivered=False,
            provider="sms",
            detail=str(exc),
        )
