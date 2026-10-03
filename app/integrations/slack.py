import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import settings
from app.integrations.base import NotificationResult
from app.models import Lead, LeadAnalysis

logger = logging.getLogger("leadflow.integrations.slack")


def _lead_notification(lead: Lead, analysis: LeadAnalysis, review: bool = False) -> str:
    title = "NEXORA LeadFlow — Human review required" if review else "NEXORA LeadFlow — New qualified lead"
    return "\n".join((
        title,
        f"Name: {lead.name}",
        f"Company: {lead.company or 'Not provided'}",
        f"Lead Status: {analysis.lead_status}",
        f"Service Fit: {analysis.service_fit}",
        f"Intent: {analysis.intent}",
        f"Urgency: {analysis.urgency}",
        f"Confidence: {analysis.confidence:.0%}",
        f"Recommended Action: {analysis.recommended_action}",
        f"Human Review Required: {'Yes' if analysis.human_review else 'No'}",
    ))


class MockSlackProvider:
    mode = "mock"

    def __init__(self):
        self.notifications: list[dict[str, str]] = []

    def notify_new_lead(self, lead: Lead, analysis: LeadAnalysis) -> NotificationResult:
        self.notifications.append({"kind": "new_lead", "text": _lead_notification(lead, analysis)})
        return NotificationResult(True, self.mode)

    def notify_human_review_required(self, lead: Lead, analysis: LeadAnalysis) -> NotificationResult:
        self.notifications.append({"kind": "human_review", "text": _lead_notification(lead, analysis, True)})
        return NotificationResult(True, self.mode)

    def notify_integration_error(self, integration: str, error_category: str) -> NotificationResult:
        self.notifications.append({"kind": "integration_error", "text": f"{integration} integration failed ({error_category})."})
        return NotificationResult(True, self.mode)


class SlackWebhookProvider:
    mode = "live"

    def __init__(self, webhook_url: str, timeout: float | None = None):
        self._webhook_url = webhook_url
        self._timeout = timeout or settings.integration_timeout_seconds

    def _send(self, text: str) -> NotificationResult:
        request = Request(self._webhook_url, data=json.dumps({"text": text}).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self._timeout) as response:
                return NotificationResult(200 <= response.status < 300, self.mode,
                                          None if 200 <= response.status < 300 else f"http_{response.status}")
        except HTTPError as exc:
            logger.warning("slack_webhook_failed status=%s", exc.code)
            return NotificationResult(False, self.mode, f"http_{exc.code}")
        except (TimeoutError, URLError):
            return NotificationResult(False, self.mode, "connection_error")
        except Exception as exc:
            logger.warning("slack_webhook_failed error_type=%s", type(exc).__name__)
            return NotificationResult(False, self.mode, type(exc).__name__)

    def notify_new_lead(self, lead: Lead, analysis: LeadAnalysis) -> NotificationResult:
        return self._send(_lead_notification(lead, analysis))

    def notify_human_review_required(self, lead: Lead, analysis: LeadAnalysis) -> NotificationResult:
        return self._send(_lead_notification(lead, analysis, True))

    def notify_integration_error(self, integration: str, error_category: str) -> NotificationResult:
        return self._send(f"NEXORA LeadFlow integration alert: {integration} failed ({error_category}).")


class UnconfiguredSlackProvider:
    mode = "unconfigured"

    def notify_new_lead(self, lead: Lead, analysis: LeadAnalysis) -> NotificationResult:
        return NotificationResult(False, self.mode, "missing_webhook_url")

    def notify_human_review_required(self, lead: Lead, analysis: LeadAnalysis) -> NotificationResult:
        return NotificationResult(False, self.mode, "missing_webhook_url")

    def notify_integration_error(self, integration: str, error_category: str) -> NotificationResult:
        return NotificationResult(False, self.mode, "missing_webhook_url")
