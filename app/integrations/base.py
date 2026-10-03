from dataclasses import dataclass
from typing import Protocol

from app.models import Lead, LeadAnalysis


@dataclass(frozen=True)
class CRMResult:
    success: bool
    mode: str
    external_contact_id: str | None = None
    external_company_id: str | None = None
    error_category: str | None = None


@dataclass(frozen=True)
class NotificationResult:
    success: bool
    mode: str
    error_category: str | None = None


@dataclass(frozen=True)
class EmailResult:
    success: bool
    provider: str
    status: str
    message_id: str | None = None
    error_category: str | None = None


class CRMProvider(Protocol):
    mode: str

    def sync_lead(self, lead: Lead) -> CRMResult: ...


class NotificationProvider(Protocol):
    mode: str

    def notify_new_lead(self, lead: Lead, analysis: LeadAnalysis) -> NotificationResult: ...
    def notify_human_review_required(self, lead: Lead, analysis: LeadAnalysis) -> NotificationResult: ...
    def notify_integration_error(self, integration: str, error_category: str) -> NotificationResult: ...


class EmailProvider(Protocol):
    mode: str

    def send_email(self, recipient: str, subject: str, body: str, lead_id: int,
                   analysis_id: int) -> EmailResult: ...
