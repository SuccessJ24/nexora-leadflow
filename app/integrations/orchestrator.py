import logging
import re

from sqlalchemy.orm import Session

from app.config import settings
from app.integrations.factory import get_email_provider, get_hubspot_provider, get_slack_provider
from app.models import Lead, LeadAnalysis, WorkflowEvent

logger = logging.getLogger("leadflow.integrations")


def _event(db: Session, lead_id: int, event_type: str, data: dict) -> None:
    db.add(WorkflowEvent(lead_id=lead_id, event_type=event_type, event_data=data))


def _safe_category(category: str | None) -> str:
    category = category or "integration_error"
    return category if re.fullmatch(r"(?:http_\d{3}|[A-Za-z][A-Za-z0-9_]{0,39})", category) else "integration_error"


def _send_notification(db: Session, provider, lead: Lead, analysis: LeadAnalysis, method: str, *,
                       success_event: str, failed_event: str, **kwargs) -> str | None:
    if provider.mode == "disabled":
        return None
    _event(db, lead.id, "SLACK_NOTIFICATION_STARTED", {"kind": method, "mode": provider.mode})
    db.commit()
    try:
        if method == "notify_integration_error":
            result = getattr(provider, method)(**kwargs)
        else:
            result = getattr(provider, method)(lead, analysis)
    except Exception as exc:
        logger.warning("slack_notification_failed error_type=%s", type(exc).__name__)
        result = None
        category = type(exc).__name__
    else:
        category = _safe_category(result.error_category)
    if result and result.success:
        _event(db, lead.id, success_event, {"kind": method, "mode": result.mode})
    else:
        _event(db, lead.id, failed_event, {"kind": method, "category": category})
        logger.warning("slack_notification_failed category=%s", category)
        db.commit()
        return category
    db.commit()
    return None


def process_integrations(db: Session, lead: Lead, analysis: LeadAnalysis) -> None:
    """Run optional CRM and sales-notification steps without blocking lead processing."""
    crm = get_hubspot_provider()
    if crm.mode == "disabled":
        _event(db, lead.id, "CRM_SYNC_SKIPPED", {"reason": "disabled"})
        db.commit()
        crm_error = None
    elif analysis.lead_status == "UNQUALIFIED":
        _event(db, lead.id, "CRM_SYNC_SKIPPED", {"reason": "not_qualified"})
        db.commit()
        crm_error = None
    else:
        _event(db, lead.id, "CRM_SYNC_STARTED", {"mode": crm.mode})
        db.commit()
        try:
            result = crm.sync_lead(lead)
        except Exception as exc:
            logger.warning("hubspot_sync_failed error_type=%s", type(exc).__name__)
            result = None
            crm_error = type(exc).__name__
        else:
            crm_error = _safe_category(result.error_category)
        if result and result.success:
            _event(db, lead.id, "CRM_SYNC_COMPLETED", {
                "mode": result.mode,
                "external_contact_id": result.external_contact_id,
                "external_company_id": result.external_company_id,
            })
            crm_error = None
        else:
            _event(db, lead.id, "CRM_SYNC_FAILED", {"category": crm_error})
            logger.warning("hubspot_sync_failed category=%s", crm_error)
        db.commit()

    slack = get_slack_provider()
    if slack.mode == "disabled":
        _event(db, lead.id, "SLACK_NOTIFICATION_SKIPPED", {"reason": "disabled"})
        db.commit()
        return

    if crm_error:
        error = _send_notification(db, slack, lead, analysis, "notify_integration_error",
            success_event="SLACK_NOTIFICATION_SENT", failed_event="SLACK_NOTIFICATION_FAILED",
            integration="hubspot", error_category=crm_error)
        if error:
            logger.warning("integration_error_notification_failed category=%s", error)

    if analysis.lead_status in ("HOT", "WARM"):
        error = _send_notification(db, slack, lead, analysis, "notify_new_lead",
            success_event="SLACK_NOTIFICATION_SENT", failed_event="SLACK_NOTIFICATION_FAILED")
        if error:
            logger.warning("new_lead_notification_failed category=%s", error)
    else:
        _event(db, lead.id, "SLACK_NOTIFICATION_SKIPPED", {"reason": "not_qualified"})
        db.commit()

    if analysis.human_review:
        error = _send_notification(db, slack, lead, analysis, "notify_human_review_required",
            success_event="SLACK_NOTIFICATION_SENT", failed_event="SLACK_NOTIFICATION_FAILED")
        if error:
            logger.warning("review_notification_failed category=%s", error)


def integration_health() -> dict[str, str]:
    hubspot = get_hubspot_provider()
    slack = get_slack_provider()
    # This endpoint reports selected/configured mode, not remote connectivity.
    hubspot_status = "configured" if hubspot.mode == "live" else hubspot.mode
    slack_status = "configured" if slack.mode == "live" else slack.mode
    email = get_email_provider()
    email_status = "configured" if email.mode == "resend" else email.mode
    return {"ai_provider": "mock" if settings.mock_ai else "openai",
            "hubspot": hubspot_status, "slack": slack_status, "email": email_status}
