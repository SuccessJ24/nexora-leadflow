from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator


class LeadStatus(StrEnum):
    HOT = "HOT"
    WARM = "WARM"
    NURTURE = "NURTURE"
    UNQUALIFIED = "UNQUALIFIED"


class Fit(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class BudgetFit(StrEnum):
    GOOD = "GOOD"
    UNCLEAR = "UNCLEAR"
    POOR = "POOR"


class Action(StrEnum):
    SALES_CALL = "SALES_CALL"
    FOLLOW_UP = "FOLLOW_UP"
    REQUEST_INFORMATION = "REQUEST_INFORMATION"
    NURTURE = "NURTURE"
    NO_ACTION = "NO_ACTION"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class LeadCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    company: str | None = Field(default=None, max_length=200)
    website: HttpUrl | None = None
    industry: str | None = Field(default=None, max_length=120)
    budget: str | None = Field(default=None, max_length=120)
    timeline: str | None = Field(default=None, max_length=200)
    message: str = Field(min_length=5, max_length=12000)

    @field_validator("name", "message")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field cannot be blank")
        return value


class AIAnalysis(BaseModel):
    lead_status: LeadStatus
    service_fit: Fit
    intent: Fit
    urgency: Fit
    budget_fit: BudgetFit
    confidence: float = Field(ge=0, le=1)
    summary: str = Field(min_length=1, max_length=1500)
    justification: str = Field(min_length=1, max_length=1200)
    pain_points: list[str] = Field(default_factory=list, max_length=15)
    requested_services: list[str] = Field(default_factory=list, max_length=15)
    missing_information: list[str] = Field(default_factory=list, max_length=15)
    recommended_action: Action
    human_review: bool


class DecisionRequest(BaseModel):
    decision: str = Field(pattern="^(APPROVE|REJECT|REQUEST_INFORMATION|RECLASSIFY)$")
    notes: str | None = Field(default=None, max_length=2000)
    new_status: LeadStatus | None = None


class AnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lead_status: str
    service_fit: str
    intent: str
    urgency: str
    budget_fit: str
    confidence: float
    summary: str
    justification: str
    pain_points: list[str]
    requested_services: list[str]
    missing_information: list[str]
    recommended_action: str
    human_review: bool
    review_reason: str | None
    response_draft: str
    created_at: datetime


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    company: str | None
    website: str | None
    industry: str | None
    budget: str | None
    timeline: str | None
    message: str
    created_at: datetime
    updated_at: datetime
    latest_analysis: AnalysisOut | None = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_type: str
    event_data: dict
    created_at: datetime


class LeadDetail(LeadOut):
    events: list[EventOut]


class DashboardSummary(BaseModel):
    total_leads: int
    hot_leads: int
    warm_leads: int
    nurture_leads: int
    human_review_required: int
    follow_ups_due: int
