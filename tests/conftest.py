import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db
from app.config import settings
from app.main import app
from app.schemas import AIAnalysis, Action, BudgetFit, Fit, LeadStatus
from app.services import analyze_with_openai


@pytest.fixture(autouse=True)
def default_to_real_provider(monkeypatch):
    # Keep existing OpenAI adapter tests deterministic regardless of local .env.
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "hubspot_enabled", False)
    monkeypatch.setattr(settings, "slack_enabled", False)
    monkeypatch.setattr(settings, "resend_enabled", False)
    monkeypatch.setattr(settings, "hubspot_access_token", None)
    monkeypatch.setattr(settings, "slack_webhook_url", None)
    monkeypatch.setattr(settings, "resend_api_key", None)
    monkeypatch.setattr(settings, "resend_from_email", None)
    monkeypatch.setattr(settings, "app_env", "development")

@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()

@pytest.fixture
def client(engine):
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

@pytest.fixture
def ai_result():
    def build(**overrides):
        data = {
            "lead_status": LeadStatus.HOT, "service_fit": Fit.HIGH, "intent": Fit.HIGH,
            "urgency": Fit.HIGH, "budget_fit": BudgetFit.GOOD, "confidence": 0.92,
            "summary": "Needs paid advertising and LinkedIn lead generation.",
            "justification": "Strong service fit, explicit request, and near-term launch.",
            "pain_points": ["Campaign launch support"], "requested_services": ["Paid advertising", "LinkedIn lead generation"],
            "missing_information": [], "recommended_action": Action.SALES_CALL, "human_review": False,
        }
        data.update(overrides)
        return AIAnalysis.model_validate(data)
    return build

@pytest.fixture
def mock_ai(monkeypatch, ai_result):
    monkeypatch.setattr("app.services.analyze_with_openai", lambda lead: ai_result())
    return ai_result

