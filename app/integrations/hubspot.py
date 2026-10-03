import json
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.config import settings
from app.integrations.base import CRMResult
from app.models import Lead

logger = logging.getLogger("leadflow.integrations.hubspot")


class MockHubSpotProvider:
    mode = "mock"

    def __init__(self):
        self.contacts: dict[str, str] = {}
        self.companies: dict[str, str] = {}
        self.associations: set[tuple[str, str]] = set()

    def create_or_update_contact(self, lead: Lead) -> str:
        key = lead.email.lower()
        if key not in self.contacts:
            self.contacts[key] = f"mock-contact-{len(self.contacts) + 1:06d}"
        return self.contacts[key]

    def create_or_update_company(self, lead: Lead) -> str | None:
        if not lead.company:
            return None
        key = urlparse(lead.website or "").hostname or lead.company.lower()
        if key not in self.companies:
            self.companies[key] = f"mock-company-{len(self.companies) + 1:06d}"
        return self.companies[key]

    def attach_lead_to_crm(self, contact_id: str, company_id: str | None) -> None:
        if company_id:
            self.associations.add((contact_id, company_id))

    def sync_lead(self, lead: Lead) -> CRMResult:
        contact_id = self.create_or_update_contact(lead)
        company_id = self.create_or_update_company(lead)
        self.attach_lead_to_crm(contact_id, company_id)
        return CRMResult(True, self.mode, contact_id, company_id)


class HubSpotProvider:
    """HubSpot CRM object upserts; credentials and response bodies are never logged."""
    mode = "live"

    def __init__(self, access_token: str, timeout: float | None = None):
        self._access_token = access_token
        self._timeout = timeout or settings.integration_timeout_seconds

    def _request(self, method: str, path: str, payload: dict) -> dict:
        request = Request(
            f"https://api.hubapi.com{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self._access_token}", "Content-Type": "application/json"},
            method=method,
        )
        with urlopen(request, timeout=self._timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def create_or_update_contact(self, lead: Lead) -> str:
        result = self._request("POST", "/crm/v3/objects/contacts/batch/upsert", {"inputs": [{
            "id": lead.email, "idProperty": "email", "properties": {
                "email": lead.email, "firstname": lead.name.split()[0],
                "lastname": " ".join(lead.name.split()[1:]),
                **({"company": lead.company} if lead.company else {}),
                **({"website": lead.website} if lead.website else {}),
                **({"industry": lead.industry} if lead.industry else {}),
            },
        }]})
        return str(result["results"][0]["id"])

    def create_or_update_company(self, lead: Lead) -> str | None:
        if not lead.company:
            return None
        domain = urlparse(lead.website or "").hostname
        if not domain:
            return None
        result = self._request("POST", "/crm/v3/objects/companies/batch/upsert", {"inputs": [{
            "id": domain, "idProperty": "domain", "properties": {
                "name": lead.company, "domain": domain, "website": lead.website,
                **({"industry": lead.industry} if lead.industry else {}),
            },
        }]})
        return str(result["results"][0]["id"])

    def attach_lead_to_crm(self, contact_id: str, company_id: str | None) -> None:
        if company_id:
            self._request("PUT", f"/crm/v4/objects/contacts/{contact_id}/associations/default/companies/{company_id}", {})

    def sync_lead(self, lead: Lead) -> CRMResult:
        try:
            contact_id = self.create_or_update_contact(lead)
            company_id = self.create_or_update_company(lead)
            self.attach_lead_to_crm(contact_id, company_id)
            return CRMResult(True, self.mode, contact_id, company_id)
        except HTTPError as exc:
            logger.warning("hubspot_request_failed status=%s", exc.code)
            return CRMResult(False, self.mode, error_category=f"http_{exc.code}")
        except (TimeoutError, URLError):
            return CRMResult(False, self.mode, error_category="connection_error")
        except (KeyError, IndexError, TypeError, ValueError):
            return CRMResult(False, self.mode, error_category="malformed_response")
        except Exception as exc:
            logger.warning("hubspot_request_failed error_type=%s", type(exc).__name__)
            return CRMResult(False, self.mode, error_category=type(exc).__name__)


class UnconfiguredHubSpotProvider:
    mode = "unconfigured"

    def sync_lead(self, lead: Lead) -> CRMResult:
        return CRMResult(False, self.mode, error_category="missing_access_token")
