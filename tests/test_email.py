import json
from types import SimpleNamespace

import pytest

from app.config import settings
from app.integrations.email import (
    DisabledEmailProvider, MockEmailProvider, ResendEmailProvider,
    UnconfiguredResendProvider, mock_message_id,
)
from app.integrations.factory import get_email_provider


def lead_payload():
    return {
        "name": "Sarah Johnson", "email": "sarah@example.com", "company": "FinTechPro",
        "industry": "Fintech", "budget": "$5,000/month", "timeline": "Within 30 days",
        "message": "We need paid advertising and LinkedIn lead generation.",
    }


def test_email_factory_selects_mock_disabled_resend_and_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", True)
    monkeypatch.setattr(settings, "resend_enabled", True)
    monkeypatch.setattr(settings, "app_env", "development")
    assert isinstance(get_email_provider(), MockEmailProvider)

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "resend_api_key", "test-key")
    monkeypatch.setattr(settings, "resend_from_email", "Nexora <hello@example.com>")
    assert isinstance(get_email_provider(), ResendEmailProvider)

    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "resend_enabled", False)
    assert isinstance(get_email_provider(), DisabledEmailProvider)

    monkeypatch.setattr(settings, "resend_enabled", True)
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "resend_api_key", None)
    monkeypatch.setattr(settings, "resend_from_email", None)
    assert isinstance(get_email_provider(), UnconfiguredResendProvider)
    monkeypatch.setattr(settings, "resend_api_key", "test-key")
    monkeypatch.setattr(settings, "resend_from_email", "Nexora <hello@example.com>")
    assert isinstance(get_email_provider(), ResendEmailProvider)


def test_mock_email_is_deterministic_and_captures_without_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Mock email must not make network requests")

    monkeypatch.setattr("app.integrations.email.urlopen", forbidden)
    provider = MockEmailProvider()
    result = provider.send_email("sarah@example.com", "Hello", "Approved draft", 7, 9)
    assert result.success and result.provider == "mock" and result.status == "sent"
    assert result.message_id == mock_message_id(7, 9) == "mock-email-000007-000009"
    assert provider.sent[0]["body"] == "Approved draft"


def test_resend_uses_configured_endpoint_without_logging_key(monkeypatch, caplog):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"id":"re_mock123"}'

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("app.integrations.email.urlopen", fake_urlopen)
    secret = "resend-secret-test-value"
    result = ResendEmailProvider(secret, "Nexora <hello@example.com>").send_email(
        "sarah@example.com", "Hello", "Approved body", 2, 3
    )
    assert result.success and result.message_id == "re_mock123"
    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["auth"] == f"Bearer {secret}"
    assert captured["payload"]["text"] == "Approved body"
    assert secret not in caplog.text


def test_lead_creation_never_sends_and_approval_sends_once(client, monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", True)
    provider = MockEmailProvider()
    monkeypatch.setattr("app.main.get_email_provider", lambda: provider)

    created = client.post("/api/leads", json=lead_payload())
    assert created.status_code == 201
    assert provider.sent == []
    analysis = created.json()["latest_analysis"]
    approval = client.post("/api/leads/1/approve")
    assert approval.status_code == 200
    assert approval.json() == {
        "status": "sent", "provider": "mock",
        "message_id": mock_message_id(1, analysis["id"]),
    }
    assert len(provider.sent) == 1
    assert provider.sent[0]["body"] == analysis["response_draft"]
    duplicate = client.post("/api/leads/1/approve")
    assert duplicate.status_code == 200 and duplicate.json()["status"] == "already_sent"
    assert len(provider.sent) == 1
    event_types = [e["event_type"] for e in client.get("/api/leads/1").json()["events"]]
    assert "HUMAN_DECISION" in event_types
    assert "EMAIL_APPROVAL_GRANTED" in event_types
    assert "EMAIL_SEND_STARTED" in event_types
    assert "EMAIL_SENT" in event_types


def test_complete_mock_business_workflow(client, monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", True)
    monkeypatch.setattr(settings, "hubspot_enabled", True)
    monkeypatch.setattr(settings, "slack_enabled", True)
    email = MockEmailProvider()
    monkeypatch.setattr("app.main.get_email_provider", lambda: email)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Mock workflow must not make outbound HTTP calls")

    monkeypatch.setattr("app.integrations.hubspot.urlopen", forbidden)
    monkeypatch.setattr("app.integrations.slack.urlopen", forbidden)
    monkeypatch.setattr("app.integrations.email.urlopen", forbidden)

    response = client.post("/api/leads", json={
        "name": "Taylor Example", "email": "taylor@example.com", "message": "Need help with growth."
    })
    assert response.status_code == 201
    assert response.json()["latest_analysis"]["human_review"] is True
    assert email.sent == []
    detail = client.get("/api/leads/1").json()
    kinds = [event["event_type"] for event in detail["events"]]
    for expected in (
        "LEAD_RECEIVED", "AI_ANALYSIS_STARTED", "AI_ANALYSIS_COMPLETED",
        "QUALIFICATION_COMPLETED", "CRM_SYNC_STARTED", "CRM_SYNC_COMPLETED",
        "HUMAN_REVIEW_REQUIRED", "SLACK_NOTIFICATION_SENT", "EMAIL_DRAFT_CREATED",
    ):
        assert expected in kinds

    sent = client.post("/api/leads/1/approve")
    assert sent.status_code == 200 and sent.json()["status"] == "sent"
    assert len(email.sent) == 1
    after = client.get("/api/leads/1").json()
    after_kinds = [event["event_type"] for event in after["events"]]
    assert after_kinds.index("EMAIL_APPROVAL_GRANTED") < after_kinds.index("EMAIL_SENT")
    assert "EMAIL_SENT" in after_kinds


@pytest.mark.parametrize("decision,event_name", [
    ("REJECT", "EMAIL_APPROVAL_REJECTED"),
    ("REQUEST_INFORMATION", "EMAIL_APPROVAL_INFORMATION_REQUESTED"),
])
def test_reject_and_request_information_never_send(client, monkeypatch, decision, event_name):
    monkeypatch.setattr(settings, "mock_ai", True)
    provider = MockEmailProvider()
    monkeypatch.setattr("app.main.get_email_provider", lambda: provider)
    assert client.post("/api/leads", json=lead_payload()).status_code == 201
    response = client.post("/api/leads/1/review", json={"decision": decision})
    assert response.status_code == 200
    events = client.get("/api/leads/1").json()["events"]
    assert any(e["event_type"] == event_name for e in events)
    assert any(e["event_type"] == "EMAIL_SEND_SKIPPED" for e in events)
    assert provider.sent == []


def test_failed_email_is_logged_safely_and_can_be_retried(client, monkeypatch, caplog):
    monkeypatch.setattr(settings, "mock_ai", True)

    class FlakyEmail:
        mode = "mock"
        attempts = 0

        def send_email(self, *_args):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("secret-key and private body")
            from app.integrations.base import EmailResult
            return EmailResult(True, "mock", "sent", "mock-retry-id")

    provider = FlakyEmail()
    monkeypatch.setattr("app.main.get_email_provider", lambda: provider)
    assert client.post("/api/leads", json=lead_payload()).status_code == 201
    failed = client.post("/api/leads/1/approve")
    assert failed.status_code == 502
    assert "secret-key" not in failed.text and "private body" not in failed.text
    assert "secret-key" not in caplog.text and "private body" not in caplog.text
    events = client.get("/api/leads/1").json()["events"]
    assert any(e["event_type"] == "EMAIL_SEND_FAILED" for e in events)
    assert "secret-key" not in str(events)
    retried = client.post("/api/leads/1/approve")
    assert retried.status_code == 200 and retried.json()["status"] == "sent"
    assert provider.attempts == 2


def test_approval_rejects_missing_or_ineligible_leads(client, mock_ai, engine):
    assert client.post("/api/leads/999/approve").status_code == 404
    assert client.post("/api/leads", json=lead_payload()).status_code == 201
    from sqlalchemy.orm import Session
    from app.models import LeadAnalysis
    with Session(engine) as db:
        analysis = db.query(LeadAnalysis).one()
        analysis.response_draft = ""
        db.commit()
    assert client.post("/api/leads/1/approve").status_code == 409
    with Session(engine) as db:
        analysis = db.query(LeadAnalysis).one()
        analysis.response_draft = "Approved draft body"
        analysis.lead_status = "UNQUALIFIED"
        db.commit()
    assert client.post("/api/leads/1/approve").status_code == 409


def test_health_and_dashboard_expose_safe_email_status(client, monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", True)
    health = client.get("/api/health").json()
    assert health["integrations"]["email"] == "mock"
    page = client.get("/").text
    assert "integrations.email" in page
    assert "Approve &amp; Send" in page
    assert "Not sent" in page
