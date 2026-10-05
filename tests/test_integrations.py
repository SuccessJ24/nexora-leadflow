import pytest

from app.config import settings
from app.integrations.base import CRMResult
from app.integrations.factory import get_hubspot_provider, get_slack_provider
from app.integrations.hubspot import MockHubSpotProvider, HubSpotProvider
from app.integrations.slack import MockSlackProvider, SlackWebhookProvider


def payload():
    return {
        "name": "Sarah Johnson", "email": "sarah@example.com", "company": "FinTechPro",
        "website": "https://fintechpro.example", "industry": "Fintech", "budget": "$5,000/month",
        "timeline": "Within 30 days", "message": "We need paid advertising and LinkedIn lead generation.",
    }


def test_provider_selection_uses_mock_or_live(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", True)
    monkeypatch.setattr(settings, "hubspot_enabled", True)
    monkeypatch.setattr(settings, "slack_enabled", True)
    monkeypatch.setattr(settings, "hubspot_access_token", None)
    monkeypatch.setattr(settings, "slack_webhook_url", None)
    assert isinstance(get_hubspot_provider(), MockHubSpotProvider)
    assert isinstance(get_slack_provider(), MockSlackProvider)

    monkeypatch.setattr(settings, "hubspot_access_token", "test-token")
    monkeypatch.setattr(settings, "slack_webhook_url", "https://hooks.slack.test/mock")
    assert isinstance(get_hubspot_provider(), HubSpotProvider)
    assert isinstance(get_slack_provider(), SlackWebhookProvider)
    from app.services import MockAIProvider, get_ai_provider
    assert isinstance(get_ai_provider(), MockAIProvider)


def test_mock_ai_with_configured_hubspot_reports_live_adapter(client, monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", True)
    monkeypatch.setattr(settings, "hubspot_enabled", True)
    monkeypatch.setattr(settings, "hubspot_access_token", "test-hubspot-token")
    monkeypatch.setattr("app.integrations.hubspot.urlopen", lambda *_args, **_kwargs: pytest.fail("HubSpot must not be called"))

    provider = get_hubspot_provider()
    assert isinstance(provider, HubSpotProvider)
    assert provider.mode == "live"

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["integrations"]["ai_provider"] == "mock"
    assert health.json()["integrations"]["hubspot"] == "configured"
    assert "test-hubspot-token" not in health.text


def test_mock_hubspot_upsert_and_association_are_deterministic():
    from app.models import Lead

    lead = Lead(id=1, **payload())
    provider = MockHubSpotProvider()
    first = provider.sync_lead(lead)
    second = provider.sync_lead(lead)
    assert first.success and second.success
    assert first.external_contact_id == second.external_contact_id
    assert first.external_company_id == second.external_company_id
    assert (first.external_contact_id, first.external_company_id) in provider.associations


def test_mock_mode_integrations_do_not_make_http_calls(client, monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", True)
    monkeypatch.setattr(settings, "hubspot_enabled", True)
    monkeypatch.setattr(settings, "slack_enabled", True)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("mock mode must not make HTTP calls")

    monkeypatch.setattr("app.integrations.hubspot.urlopen", forbidden)
    monkeypatch.setattr("app.integrations.slack.urlopen", forbidden)
    response = client.post("/api/leads", json=payload())
    assert response.status_code == 201
    kinds = [e["event_type"] for e in client.get("/api/leads/1").json()["events"]]
    assert "CRM_SYNC_COMPLETED" in kinds
    assert "SLACK_NOTIFICATION_SENT" in kinds


def test_mock_slack_captures_qualified_and_review_messages():
    from app.models import Lead, LeadAnalysis

    lead = Lead(id=1, **payload())
    analysis = LeadAnalysis(lead_id=1, lead_status="HOT", service_fit="HIGH", intent="HIGH",
        urgency="HIGH", budget_fit="GOOD", confidence=0.9, summary="Ready", justification="Strong fit",
        pain_points=[], requested_services=["Lead generation"], missing_information=[],
        recommended_action="SALES_CALL", human_review=True, response_draft="Draft")
    provider = MockSlackProvider()
    assert provider.notify_new_lead(lead, analysis).success
    assert provider.notify_human_review_required(lead, analysis).success
    assert [n["kind"] for n in provider.notifications] == ["new_lead", "human_review"]
    assert "Confidence: 90%" in provider.notifications[0]["text"]
    assert "Human review required" in provider.notifications[1]["text"]


def test_hubspot_failure_is_logged_and_notified_without_failing_lead(client, monkeypatch):
    from app.integrations.slack import MockSlackProvider

    monkeypatch.setattr(settings, "mock_ai", True)
    monkeypatch.setattr(settings, "hubspot_enabled", True)
    monkeypatch.setattr(settings, "slack_enabled", True)

    class BrokenCRM:
        mode = "mock"

        def sync_lead(self, _lead):
            return CRMResult(False, "mock", error_category="connection_error")

    slack = MockSlackProvider()
    monkeypatch.setattr("app.integrations.orchestrator.get_hubspot_provider", lambda: BrokenCRM())
    monkeypatch.setattr("app.integrations.orchestrator.get_slack_provider", lambda: slack)
    response = client.post("/api/leads", json=payload())
    assert response.status_code == 201
    assert response.json()["latest_analysis"] is not None
    events = client.get("/api/leads/1").json()["events"]
    assert any(e["event_type"] == "CRM_SYNC_FAILED" for e in events)
    assert any(e["event_type"] == "SLACK_NOTIFICATION_SENT" for e in events)
    assert {n["kind"] for n in slack.notifications} == {"integration_error", "new_lead"}


def test_slack_failure_is_logged_without_failing_lead(client, monkeypatch):
    from app.integrations.base import NotificationResult

    monkeypatch.setattr(settings, "mock_ai", True)
    monkeypatch.setattr(settings, "slack_enabled", True)

    class BrokenSlack:
        mode = "mock"

        def notify_new_lead(self, _lead, _analysis):
            return NotificationResult(False, "mock", "connection_error")

        def notify_human_review_required(self, _lead, _analysis):
            return NotificationResult(False, "mock", "connection_error")

        def notify_integration_error(self, **_kwargs):
            return NotificationResult(False, "mock", "connection_error")

    monkeypatch.setattr("app.integrations.orchestrator.get_slack_provider", lambda: BrokenSlack())
    response = client.post("/api/leads", json=payload())
    assert response.status_code == 201
    events = client.get("/api/leads/1").json()["events"]
    assert any(e["event_type"] == "SLACK_NOTIFICATION_FAILED" for e in events)


def test_mock_human_review_still_notifies_reviewers(client, monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", True)
    monkeypatch.setattr(settings, "slack_enabled", True)
    response = client.post("/api/leads", json={"name": "Lee", "email": "lee@example.com", "message": "Need help"})
    assert response.status_code == 201
    assert response.json()["latest_analysis"]["human_review"] is True
    events = [e["event_type"] for e in client.get("/api/leads/1").json()["events"]]
    assert "HUMAN_REVIEW_REQUIRED" in events
    assert events.count("SLACK_NOTIFICATION_SENT") == 1


def test_provider_errors_never_log_credentials_or_payload(monkeypatch, caplog):
    from urllib.error import URLError
    from app.integrations.slack import SlackWebhookProvider
    from app.models import Lead

    token = "credential-must-not-appear"
    secret_url = f"https://hooks.slack.test/{token}"

    def failed_request(*_args, **_kwargs):
        raise URLError(f"{token} private lead payload")

    monkeypatch.setattr("app.integrations.hubspot.urlopen", failed_request)
    monkeypatch.setattr("app.integrations.slack.urlopen", failed_request)
    lead = Lead(id=1, **payload())
    assert HubSpotProvider(token).sync_lead(lead).success is False
    assert SlackWebhookProvider(secret_url).notify_integration_error("hubspot", "connection_error").success is False
    assert token not in caplog.text
    assert "private lead payload" not in caplog.text
    assert secret_url not in caplog.text


def test_disabled_integrations_are_reported_in_events(client, mock_ai):
    response = client.post("/api/leads", json=payload())
    assert response.status_code == 201
    events = [e["event_type"] for e in client.get("/api/leads/1").json()["events"]]
    assert "CRM_SYNC_SKIPPED" in events
    assert "SLACK_NOTIFICATION_SKIPPED" in events


def test_health_reports_modes_without_credentials(client, monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "hubspot_enabled", True)
    monkeypatch.setattr(settings, "slack_enabled", True)
    monkeypatch.setattr(settings, "hubspot_access_token", "credential-must-not-leak")
    monkeypatch.setattr(settings, "slack_webhook_url", "https://secret.example/webhook-token")
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["integrations"] == {"ai_provider": "openai", "hubspot": "configured", "slack": "configured", "email": "disabled"}
    assert "credential-must-not-leak" not in response.text
    assert "webhook-token" not in response.text
