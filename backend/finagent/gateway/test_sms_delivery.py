import sys
import types

from finagent.gateway.sms_delivery import send_sms_message


def test_send_sms_message_reports_unconfigured(monkeypatch):
    for key in [
        "ACS_SMS_CONNECTION_STRING",
        "ACS_EMAIL_CONNECTION_STRING",
        "AZURE_COMMUNICATION_CONNECTION_STRING",
        "ACS_SMS_FROM",
    ]:
        monkeypatch.delenv(key, raising=False)

    outcome = send_sms_message(
        to_phone="+919876543210",
        message="ProspektLab verification code: 123456",
    )

    assert outcome.delivered is False
    assert outcome.provider == "sms"
    assert "configured" in outcome.detail.lower()


def test_send_sms_message_uses_acs(monkeypatch):
    class FakeSmsResult:
        successful = True
        message_id = "sms-message-123"

    class FakeSmsClient:
        last_connection_string = None
        last_payload = None

        @classmethod
        def from_connection_string(cls, connection_string):
            cls.last_connection_string = connection_string
            return cls()

        def send(self, **kwargs):
            type(self).last_payload = kwargs
            return [FakeSmsResult()]

    azure_module = types.ModuleType("azure")
    communication_module = types.ModuleType("azure.communication")
    sms_module = types.ModuleType("azure.communication.sms")
    sms_module.SmsClient = FakeSmsClient
    azure_module.communication = communication_module
    communication_module.sms = sms_module

    monkeypatch.setitem(sys.modules, "azure", azure_module)
    monkeypatch.setitem(sys.modules, "azure.communication", communication_module)
    monkeypatch.setitem(sys.modules, "azure.communication.sms", sms_module)
    monkeypatch.setenv("ACS_SMS_CONNECTION_STRING", "endpoint=https://example.communication.azure.com/;accesskey=test")
    monkeypatch.setenv("ACS_SMS_FROM", "+15551234567")

    outcome = send_sms_message(
        to_phone="+919876543210",
        message="ProspektLab verification code: 123456",
    )

    assert outcome.delivered is True
    assert outcome.provider == "sms"
    assert outcome.detail == "sms-message-123"
    assert FakeSmsClient.last_connection_string.startswith("endpoint=https://example.communication.azure.com/")
    assert FakeSmsClient.last_payload["from_"] == "+15551234567"
    assert FakeSmsClient.last_payload["to"] == ["+919876543210"]
