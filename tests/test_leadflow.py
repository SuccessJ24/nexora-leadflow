import pytest
from pydantic import ValidationError
from app.schemas import AIAnalysis, Action, BudgetFit, Fit, LeadCreate, LeadStatus
from app.models import Lead
from app.services import MockAIProvider, OpenAIProvider, get_ai_provider, qualify

def payload(**updates):
    value = {"name":"Sarah Johnson","email":"sarah@example.com","company":"FinTechPro","industry":"Fintech",
             "budget":"$5,000-$10,000/month","timeline":"Within 30 days",
             "message":"We need paid advertising and LinkedIn lead generation for our launch."}
    value.update(updates)
    return value

def lead_obj(**updates):
    return Lead(id=1, **payload(**updates))

def test_valid_lead_submission_and_database_persistence(client, mock_ai):
    response = client.post("/api/leads", json=payload())
    assert response.status_code == 201
    body = response.json()
    assert body["id"] and body["latest_analysis"]["lead_status"] == "HOT"
    assert body["latest_analysis"]["response_draft"]
    assert client.get("/api/leads").json()[0]["email"] == "sarah@example.com"

def test_invalid_input_rejected(client):
    assert client.post("/api/leads", json=payload(email="not-an-email")).status_code == 422
    assert client.post("/api/leads", json=payload(message=" ")).status_code == 422

@pytest.mark.parametrize(("values","expected"), [
    ({}, "HOT"),
    ({"service_fit":Fit.MEDIUM,"intent":Fit.HIGH,"urgency":Fit.MEDIUM}, "WARM"),
    ({"intent":Fit.LOW,"urgency":Fit.LOW}, "NURTURE"),
    ({"lead_status":LeadStatus.UNQUALIFIED,"service_fit":Fit.LOW}, "UNQUALIFIED"),
])
def test_deterministic_qualification(ai_result, values, expected):
    status, _, _, _ = qualify(ai_result(**values), lead_obj())
    assert status.value == expected

def test_missing_information_prevents_hot_and_requests_information(ai_result):
    status, action, _, _ = qualify(ai_result(missing_information=["monthly target"]), lead_obj())
    assert status.value == "WARM"
    assert action.value == "REQUEST_INFORMATION"

def test_low_confidence_routes_to_review(ai_result, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ai_confidence_threshold", 0.65)
    status, action, review, reason = qualify(ai_result(confidence=0.2), lead_obj())
    assert status.value == "HOT"
    assert action.value == "HUMAN_REVIEW"
    assert review and "confidence" in reason

def test_high_value_routes_to_review(ai_result):
    _, action, review, reason = qualify(ai_result(), lead_obj(budget="$30,000/month"))
    assert review and action.value == "HUMAN_REVIEW" and "high-value" in reason

def test_ai_schema_validation_rejects_bad_confidence(ai_result):
    data = ai_result().model_dump()
    data["confidence"] = 1.5
    with pytest.raises(ValidationError):
        AIAnalysis.model_validate(data)

def test_dashboard_summary(client, mock_ai):
    client.post("/api/leads", json=payload())
    summary = client.get("/api/dashboard/summary")
    assert summary.status_code == 200
    assert summary.json()["total_leads"] == 1
    assert summary.json()["hot_leads"] == 1

def test_reanalysis_persists_new_analysis(client, monkeypatch, ai_result):
    monkeypatch.setattr("app.services.analyze_with_openai", lambda lead: ai_result())
    client.post("/api/leads", json=payload())
    monkeypatch.setattr("app.services.analyze_with_openai", lambda lead: ai_result(lead_status=LeadStatus.WARM, intent=Fit.MEDIUM))
    result = client.post("/api/leads/1/reanalyze")
    assert result.status_code == 200
    assert result.json()["latest_analysis"]["lead_status"] == "WARM"
    events = client.get("/api/leads/1").json()["events"]
    assert sum(e["event_type"] == "AI_ANALYSIS_COMPLETED" for e in events) == 2

def test_human_review_decisions_are_logged(client, monkeypatch, ai_result):
    monkeypatch.setattr("app.services.analyze_with_openai", lambda lead: ai_result(confidence=0.2))
    created = client.post("/api/leads", json=payload()).json()
    assert created["latest_analysis"]["human_review"] is True
    decision = client.post("/api/leads/1/review", json={"decision":"APPROVE"})
    assert decision.status_code == 200
    detail = client.get("/api/leads/1").json()
    assert detail["latest_analysis"]["human_review"] is False
    assert any(event["event_type"] == "HUMAN_DECISION" for event in detail["events"])

def test_ai_failure_saves_lead_without_false_classification(client, monkeypatch):
    def fail(_lead):
        raise RuntimeError("provider unavailable")
    monkeypatch.setattr("app.services.analyze_with_openai", fail)
    response = client.post("/api/leads", json=payload())
    assert response.status_code == 201
    assert response.json()["latest_analysis"] is None
    events = client.get("/api/leads/1").json()["events"]
    assert any(e["event_type"] == "ERROR" for e in events)
    assert any(e["event_type"] == "HUMAN_REVIEW_REQUIRED" for e in events)

def test_malformed_ai_response_is_rejected():
    with pytest.raises(ValidationError):
        AIAnalysis.model_validate_json('{"lead_status":"HOT","confidence":9}')

def test_review_requires_status_for_reclassification(client, mock_ai):
    client.post("/api/leads", json=payload())
    assert client.post("/api/leads/1/review", json={"decision":"RECLASSIFY"}).status_code == 422

def test_database_failure_returns_safe_error(client, engine, monkeypatch):
    from app.database import get_db
    class BrokenDB:
        def execute(self, query):
            raise RuntimeError("database unavailable")
    def broken_db():
        yield BrokenDB()
    from app.main import app
    app.dependency_overrides[get_db] = broken_db
    response = client.get("/api/health")
    assert response.status_code == 503


def test_deterministic_missing_optional_fields_are_preserved(client, mock_ai):
    data = payload()
    for key in ("company", "industry", "budget", "timeline"):
        data.pop(key)
    response = client.post("/api/leads", json=data)
    analysis = response.json()["latest_analysis"]
    assert analysis["lead_status"] == "WARM"
    assert analysis["recommended_action"] == "HUMAN_REVIEW"
    assert set(("company", "industry", "budget", "timeline")).issubset(set(analysis["missing_information"]))

@pytest.mark.parametrize(("decision","extra","expected_review","expected_status"), [
    ("APPROVE", {}, False, "HOT"),
    ("REJECT", {"notes":"Need another review"}, True, "HOT"),
    ("REQUEST_INFORMATION", {}, False, "HOT"),
    ("RECLASSIFY", {"new_status":"WARM"}, False, "WARM"),
])
def test_each_human_decision_is_recorded(client, mock_ai, decision, extra, expected_review, expected_status):
    client.post("/api/leads", json=payload())
    response = client.post("/api/leads/1/review", json={"decision":decision, **extra})
    assert response.status_code == 200
    detail = client.get("/api/leads/1").json()
    assert detail["latest_analysis"]["human_review"] is expected_review
    assert detail["latest_analysis"]["lead_status"] == expected_status
    assert any(e["event_type"] == "HUMAN_DECISION" for e in detail["events"])
def test_poor_budget_fit_cannot_be_classified_hot(ai_result):
    status, action, _, _ = qualify(ai_result(budget_fit=BudgetFit.POOR), lead_obj())
    assert status.value == "WARM"
    assert action.value == "FOLLOW_UP"

def test_openai_failure_event_does_not_store_exception_text(client, monkeypatch):
    def fail(_lead):
        raise RuntimeError("sensitive-provider-detail")
    monkeypatch.setattr("app.services.analyze_with_openai", fail)
    client.post("/api/leads", json=payload())
    error = next(e for e in client.get("/api/leads/1").json()["events"] if e["event_type"] == "ERROR")
    assert "sensitive-provider-detail" not in str(error["event_data"])

def test_openai_failure_log_includes_safe_diagnostics(client, monkeypatch, caplog):
    lead_data = payload()
    api_key = "sk-proj-12345678901234567890"
    lead_message = lead_data["message"]
    def fail(_lead):
        raise RuntimeError(
            f"provider request failed; Authorization: Bearer top-secret {api_key} "
            f"email={lead_data['email']} company={lead_data['company']} {lead_message}"
        )
    monkeypatch.setattr("app.services.analyze_with_openai", fail)

    response = client.post("/api/leads", json=lead_data)

    assert response.status_code == 201
    assert "error_type=RuntimeError" in caplog.text
    assert "provider request failed" in caplog.text
    for secret in ("top-secret", api_key, lead_data["email"], lead_data["company"], lead_message, "Authorization:"):
        assert secret not in caplog.text


def demo_payload():
    return {
        "name": "David Miller",
        "email": "david@cloudscale.example",
        "company": "CloudScale SaaS",
        "website": "https://stripe.com",
        "industry": "SaaS",
        "budget": "$8,000-$15,000/month",
        "timeline": "Launching within 45 days",
        "message": (
            "We are launching a new SaaS product and need help generating qualified B2B leads. "
            "We are interested in paid advertising, LinkedIn lead generation, and improving our "
            "sales pipeline. We would like to understand your approach, expected results, and "
            "how quickly we can get started."
        ),
    }


def test_mock_provider_returns_schema_valid_structured_analysis():
    result = MockAIProvider().analyze(lead_obj(**{k: v for k, v in demo_payload().items() if k != "website"}))
    validated = AIAnalysis.model_validate(result.model_dump())
    assert validated.lead_status == LeadStatus.HOT
    assert validated.service_fit == Fit.HIGH
    assert validated.confidence >= 0.65
    assert "LinkedIn lead generation" in validated.requested_services
    assert validated.justification


def test_mock_mode_never_calls_openai_and_persists_full_workflow(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "mock_ai", True)
    def forbidden_openai(_lead):
        raise AssertionError("OpenAI must not be called in mock mode")
    monkeypatch.setattr("app.services.analyze_with_openai", forbidden_openai)

    response = client.post("/api/leads", json=demo_payload())
    assert response.status_code == 201
    analysis = response.json()["latest_analysis"]
    assert analysis["lead_status"] == "HOT"
    assert analysis["service_fit"] == "HIGH"
    assert analysis["confidence"] >= 0.65
    assert analysis["response_draft"]
    events = [e["event_type"] for e in client.get("/api/leads/1").json()["events"]]
    assert events[:5] == [
        "LEAD_RECEIVED", "AI_ANALYSIS_STARTED", "AI_ANALYSIS_COMPLETED",
        "QUALIFICATION_COMPLETED", "RESPONSE_DRAFT_GENERATED",
    ]
    assert events[-2:] == ["CRM_SYNC_SKIPPED", "SLACK_NOTIFICATION_SKIPPED"]


def test_mock_mode_routes_unclear_lead_for_review(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "mock_ai", True)
    response = client.post("/api/leads", json={"name": "Lee", "email": "lee@example.com", "message": "Need help"})
    assert response.status_code == 201
    analysis = response.json()["latest_analysis"]
    assert analysis["human_review"] is True
    assert analysis["recommended_action"] == "HUMAN_REVIEW"
    assert "HUMAN_REVIEW_REQUIRED" in [e["event_type"] for e in client.get("/api/leads/1").json()["events"]]


def test_mock_ai_false_selects_existing_openai_provider(monkeypatch, ai_result):
    from app.config import settings

    monkeypatch.setattr(settings, "mock_ai", False)
    provider = get_ai_provider()
    assert isinstance(provider, OpenAIProvider)
    monkeypatch.setattr("app.services.analyze_with_openai", lambda lead: ai_result())
    assert provider.analyze(lead_obj()).lead_status == LeadStatus.HOT


def test_mock_provider_routes_long_horizon_and_out_of_scope_leads():
    mock = MockAIProvider()
    long_horizon = mock.analyze(lead_obj(timeline="Launching in 180 days"))
    outside_scope = mock.analyze(lead_obj(message="We need legal advice for our company."))
    assert long_horizon.lead_status == LeadStatus.NURTURE
    assert outside_scope.lead_status == LeadStatus.UNQUALIFIED
