import json
import logging
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import settings
from app.integrations.base import EmailResult

logger = logging.getLogger("leadflow.integrations.email")


def mock_message_id(lead_id: int, analysis_id: int) -> str:
    return f"mock-email-{lead_id:06d}-{analysis_id:06d}"


class MockEmailProvider:
    """Captures an explicitly approved email locally without network access."""
    mode = "mock"

    def __init__(self):
        self.sent: list[dict[str, str | int]] = []

    def send_email(self, recipient: str, subject: str, body: str, lead_id: int,
                   analysis_id: int) -> EmailResult:
        message_id = mock_message_id(lead_id, analysis_id)
        self.sent.append({"recipient": recipient, "subject": subject, "body": body,
                          "lead_id": lead_id, "analysis_id": analysis_id,
                          "message_id": message_id})
        return EmailResult(True, self.mode, "sent", message_id)


class DisabledEmailProvider:
    mode = "disabled"

    def send_email(self, recipient: str, subject: str, body: str, lead_id: int,
                   analysis_id: int) -> EmailResult:
        return EmailResult(False, self.mode, "disabled", error_category="disabled")


class UnconfiguredResendProvider:
    mode = "unconfigured"

    def send_email(self, recipient: str, subject: str, body: str, lead_id: int,
                   analysis_id: int) -> EmailResult:
        return EmailResult(False, self.mode, "failed", error_category="missing_configuration")


class ResendEmailProvider:
    mode = "resend"

    def __init__(self, api_key: str, from_email: str, timeout: float | None = None):
        self._api_key = api_key
        self._from_email = from_email
        self._timeout = timeout or settings.integration_timeout_seconds

    def send_email(self, recipient: str, subject: str, body: str, lead_id: int,
                   analysis_id: int) -> EmailResult:
        payload = {"from": self._from_email, "to": [recipient], "subject": subject, "text": body}
        request = Request("https://api.resend.com/emails", data=json.dumps(payload).encode("utf-8"),
                          headers={"Authorization": f"Bearer {self._api_key}",
                                   "Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self._timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            message_id = data.get("id")
            if not isinstance(message_id, str) or not message_id:
                return EmailResult(False, self.mode, "failed", error_category="malformed_response")
            return EmailResult(True, self.mode, "sent", message_id)
        except HTTPError as exc:
            logger.warning("resend_request_failed status=%s", exc.code)
            return EmailResult(False, self.mode, "failed", error_category=f"http_{exc.code}")
        except (TimeoutError, URLError):
            return EmailResult(False, self.mode, "failed", error_category="connection_error")
        except (KeyError, TypeError, ValueError):
            return EmailResult(False, self.mode, "failed", error_category="malformed_response")
        except Exception as exc:
            # Log only a type; provider exceptions can contain request secrets or payload data.
            category = re.sub(r"[^A-Za-z0-9_]", "", type(exc).__name__)[:40] or "provider_error"
            logger.warning("resend_request_failed error_type=%s", category)
            return EmailResult(False, self.mode, "failed", error_category=category)
