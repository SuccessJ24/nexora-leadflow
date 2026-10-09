from app.config import Settings, settings
from app.services import GeminiProvider, MockAIProvider, get_ai_provider
from app.models import Lead


def test_mock_ai_true_keeps_mock_provider_even_when_gemini_selected(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", True)
    monkeypatch.setattr(settings, "ai_provider", "gemini")

    def no_live_call(*_args, **_kwargs):
        raise AssertionError("Mock mode must not call a live model provider")

    monkeypatch.setattr(GeminiProvider, "analyze", no_live_call)
    provider = get_ai_provider()
    assert isinstance(provider, MockAIProvider)


def test_gemini_provider_selected_when_live_ai_provider_is_gemini(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "ai_provider", "gemini")

    assert isinstance(get_ai_provider(), GeminiProvider)


def test_unknown_ai_provider_falls_back_to_existing_openai_adapter(monkeypatch):
    from app.services import OpenAIProvider

    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "ai_provider", "openai")

    assert isinstance(get_ai_provider(), OpenAIProvider)


def test_gemini_adapter_requests_structured_schema_without_real_network(monkeypatch, ai_result):
    import sys
    import types as pytypes

    captured = {}
    class FakeInteractions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return pytypes.SimpleNamespace(output_text=ai_result().model_dump_json())

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.interactions = FakeInteractions()

    google = pytypes.ModuleType("google")
    genai = pytypes.ModuleType("google.genai")
    genai.Client = FakeClient
    genai.types = pytypes.SimpleNamespace(HttpOptions=lambda **kwargs: kwargs)
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(settings, "gemini_model", "test-model")
    lead = Lead(id=1, name="Ava Example", email="ava@example.test", company="Example Co",
                website=None, industry="SaaS", budget=None, timeline=None,
                message="We need paid advertising support soon.")

    result = GeminiProvider().analyze(lead)

    assert result.confidence == 0.92
    assert captured["model"] == "test-model"
    assert captured["response_format"]["mime_type"] == "application/json"
    assert captured["response_format"]["schema"]["type"] == "object"
    assert "Do not infer missing details" in captured["input"]


def test_managed_postgres_url_uses_installed_psycopg_driver():
    assert Settings(database_url="postgresql://user:pass@db.example.test/leads").sqlalchemy_database_url == \
        "postgresql+psycopg://user:pass@db.example.test/leads"


def test_mock_analysis_marks_unknown_services_missing_without_inventing_them():
    lead = Lead(id=1, name="Ava Example", email="ava@example.test", company="Example Co",
                website=None, industry="SaaS", budget=None, timeline=None,
                message="We are exploring options to grow the business.")

    result = MockAIProvider().analyze(lead)

    assert result.requested_services == []
    assert "requested services" in result.missing_information
    assert "marketing support" not in result.summary


def test_gemini_key_is_redacted_from_ai_error_diagnostics(monkeypatch):
    from app.services import _safe_error_message

    monkeypatch.setattr(settings, "gemini_api_key", "AIzaSyTestSecret123456")
    lead = Lead(id=1, name="Ava Example", email="ava@example.test", company=None,
                website=None, industry=None, budget=None, timeline=None, message="Help us grow.")

    message = _safe_error_message(RuntimeError("request failed with AIzaSyTestSecret123456"), lead)

    assert "AIzaSyTestSecret123456" not in message
    assert "[REDACTED_KEY]" in message
    assert Settings(database_url="postgres://user:pass@db.example.test/leads").sqlalchemy_database_url == \
        "postgresql+psycopg://user:pass@db.example.test/leads"
