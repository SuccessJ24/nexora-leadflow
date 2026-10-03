from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://leadflow:leadflow@localhost:5432/leadflow"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    mock_ai: bool = False
    hubspot_enabled: bool = False
    hubspot_access_token: str | None = None
    slack_enabled: bool = False
    slack_webhook_url: str | None = None
    resend_enabled: bool = False
    resend_api_key: str | None = None
    resend_from_email: str | None = None
    integration_timeout_seconds: float = 5.0
    ai_confidence_threshold: float = 0.65
    high_value_budget_monthly: float = 25000
    cors_origins: str = "http://localhost:8000"
    app_env: str = "development"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
