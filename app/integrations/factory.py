from app.config import settings
from app.integrations.base import CRMProvider, NotificationProvider
from app.integrations.hubspot import HubSpotProvider, MockHubSpotProvider, UnconfiguredHubSpotProvider
from app.integrations.slack import MockSlackProvider, SlackWebhookProvider, UnconfiguredSlackProvider
from app.integrations.email import (DisabledEmailProvider, MockEmailProvider,
                                    ResendEmailProvider, UnconfiguredResendProvider)


class DisabledCRMProvider:
    mode = "disabled"


class DisabledNotificationProvider:
    mode = "disabled"


def get_hubspot_provider() -> CRMProvider | DisabledCRMProvider:
    if not settings.hubspot_enabled:
        return DisabledCRMProvider()
    if settings.hubspot_access_token:
        return HubSpotProvider(settings.hubspot_access_token)
    if settings.mock_ai:
        return MockHubSpotProvider()
    return UnconfiguredHubSpotProvider()


def get_slack_provider() -> NotificationProvider | DisabledNotificationProvider:
    if not settings.slack_enabled:
        return DisabledNotificationProvider()
    if settings.slack_webhook_url:
        return SlackWebhookProvider(settings.slack_webhook_url)
    if settings.mock_ai:
        return MockSlackProvider()
    return UnconfiguredSlackProvider()


def get_email_provider():
    production_enabled = settings.resend_enabled and settings.app_env.lower() in {"production", "prod"}
    if production_enabled:
        if settings.resend_api_key and settings.resend_from_email:
            return ResendEmailProvider(settings.resend_api_key, settings.resend_from_email)
        if settings.mock_ai:
            return MockEmailProvider()
        return UnconfiguredResendProvider()
    if settings.mock_ai:
        return MockEmailProvider()
    return DisabledEmailProvider()
