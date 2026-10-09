from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://leadflow:leadflow@localhost:5432/leadflow"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    ai_provider: str = "openai"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"
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
    auth_enabled: bool = False
    session_secret_key: str | None = None
    admin_email: str | None = None
    admin_password: str | None = None
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def workspace_auth_enabled(self) -> bool:
        return self.auth_enabled or self.app_env.lower() in {"production", "prod"}

    @property
    def sqlalchemy_database_url(self) -> str:
        # Render and many managed PostgreSQL services provide the generic scheme;
        # this project installs psycopg 3 rather than psycopg2.
        if self.database_url.startswith("postgres://"):
            return self.database_url.replace("postgres://", "postgresql+psycopg://", 1)
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        return self.database_url


settings = Settings()
