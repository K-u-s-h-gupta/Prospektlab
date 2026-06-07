import sys
import types

from finagent.gateway.email_delivery import send_email_message


def test_send_email_message_reports_unconfigured(monkeypatch):
    for key in [
        "ACS_EMAIL_CONNECTION_STRING",
        "AZURE_COMMUNICATION_CONNECTION_STRING",
        "ACS_EMAIL_FROM",
        "ACS_EMAIL_SENDER_USERNAME",
        "ACS_EMAIL_DOMAIN",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USER",
        "SMTP_PASSWORD",
        "SMTP_FROM",
    ]:
        monkeypatch.delenv(key, raising=False)

    outcome = send_email_message(
        to_email="user@example.com",
        subject="Subject",
        plain_text="Body",
    )

    assert outcome.delivered is False
    assert outcome.provider == "none"


def test_send_email_message_prefers_acs(monkeypatch):
    class FakePoller:
        def result(self):
            return {"id": "message-123"}

    class FakeEmailClient:
        last_message = None
        last_connection_string = None

        @classmethod
        def from_connection_string(cls, connection_string):
            cls.last_connection_string = connection_string
            return cls()

        def begin_send(self, message):
            type(self).last_message = message
            return FakePoller()

    azure_module = types.ModuleType("azure")
    communication_module = types.ModuleType("azure.communication")
    email_module = types.ModuleType("azure.communication.email")
    email_module.EmailClient = FakeEmailClient
    azure_module.communication = communication_module
    communication_module.email = email_module

    monkeypatch.setitem(sys.modules, "azure", azure_module)
    monkeypatch.setitem(sys.modules, "azure.communication", communication_module)
    monkeypatch.setitem(sys.modules, "azure.communication.email", email_module)

    monkeypatch.setenv("ACS_EMAIL_CONNECTION_STRING", "endpoint=https://example.communication.azure.com/;accesskey=test")
    monkeypatch.setenv("ACS_EMAIL_FROM", "outreach@notify.prospektlab.com")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)

    outcome = send_email_message(
        to_email="user@example.com",
        subject="Subject",
        plain_text="Body",
        html="<p>Body</p>",
    )

    assert outcome.delivered is True
    assert outcome.provider == "acs"
    assert FakeEmailClient.last_connection_string.startswith("endpoint=https://example.communication.azure.com/")
    assert FakeEmailClient.last_message["senderAddress"] == "outreach@notify.prospektlab.com"
    assert FakeEmailClient.last_message["recipients"]["to"][0]["address"] == "user@example.com"


def test_send_email_message_derives_sender_from_username_and_domain(monkeypatch):
    class FakePoller:
        def result(self):
            return {"id": "message-789"}

    class FakeEmailClient:
        last_message = None

        @classmethod
        def from_connection_string(cls, connection_string):
            return cls()

        def begin_send(self, message):
            type(self).last_message = message
            return FakePoller()

    azure_module = types.ModuleType("azure")
    communication_module = types.ModuleType("azure.communication")
    email_module = types.ModuleType("azure.communication.email")
    email_module.EmailClient = FakeEmailClient
    azure_module.communication = communication_module
    communication_module.email = email_module

    monkeypatch.setitem(sys.modules, "azure", azure_module)
    monkeypatch.setitem(sys.modules, "azure.communication", communication_module)
    monkeypatch.setitem(sys.modules, "azure.communication.email", email_module)

    monkeypatch.delenv("ACS_EMAIL_FROM", raising=False)
    monkeypatch.setenv("ACS_EMAIL_CONNECTION_STRING", "endpoint=https://example.communication.azure.com/;accesskey=test")
    monkeypatch.setenv("ACS_EMAIL_SENDER_USERNAME", "auth")
    monkeypatch.setenv("ACS_EMAIL_DOMAIN", "notify.prospektlab.com")

    outcome = send_email_message(
        to_email="user@example.com",
        subject="Verify",
        plain_text="Code",
    )

    assert outcome.delivered is True
    assert outcome.provider == "acs"
    assert FakeEmailClient.last_message["senderAddress"] == "auth@notify.prospektlab.com"


def test_send_email_message_falls_back_to_smtp(monkeypatch):
    class FakeSMTP:
        sent = None

        def __init__(self, host, port, timeout):
            self.host = host
            self.port = port
            self.timeout = timeout

        def starttls(self):
            return None

        def login(self, user, password):
            self.user = user
            self.password = password

        def sendmail(self, from_addr, recipients, message):
            type(self).sent = (from_addr, recipients, message)

        def quit(self):
            return None

    monkeypatch.delenv("ACS_EMAIL_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("AZURE_COMMUNICATION_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("ACS_EMAIL_FROM", raising=False)
    monkeypatch.delenv("ACS_EMAIL_SENDER_USERNAME", raising=False)
    monkeypatch.delenv("ACS_EMAIL_DOMAIN", raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "smtp-user")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-password")
    monkeypatch.setenv("SMTP_FROM", "hello@example.com")
    monkeypatch.setattr("finagent.gateway.email_delivery.smtplib.SMTP", FakeSMTP)

    outcome = send_email_message(
        to_email="user@example.com",
        subject="Subject",
        plain_text="Body",
    )

    assert outcome.delivered is True
    assert outcome.provider == "smtp"
    assert FakeSMTP.sent is not None
