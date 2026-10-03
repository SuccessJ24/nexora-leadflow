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
    if settings.mock_ai:
        return MockHubSpotProvider()
    if not settings.hubspot_access_token:
        return UnconfiguredHubSpotProvider()
    return HubSpotProvider(settings.hubspot_access_token)


def get_slack_provider() -> NotificationProvider | DisabledNotificationProvider:
    if not settings.slack_enabled:
        return DisabledNotificationProvider()
    if settings.mock_ai:
        return MockSlackProvider()
    if not settings.slack_webhook_url:
        return UnconfiguredSlackProvider()
    return SlackWebhookProvider(settings.slack_webhook_url)


def get_email_provider():
    # Mock AI mode is the local development safety boundary: never use Resend there.
    if settings.mock_ai:
        return MockEmailProvider()
    if not settings.resend_enabled:
        return DisabledEmailProvider()
    if settings.app_env.lower() not in {"production", "prod"}:
        return DisabledEmailProvider()
    if not settings.resend_api_key or not settings.resend_from_email:
        return UnconfiguredResendProvider()
    return ResendEmailProvider(settings.resend_api_key, settings.resend_from_email)
