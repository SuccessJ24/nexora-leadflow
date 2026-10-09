from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hmac
import logging
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from app.database import get_db
from app.config import settings
from app.security import SignedSessionMiddleware
from app.models import FollowUp, Lead, LeadAnalysis, WorkflowEvent
from app.schemas import DashboardSummary, DecisionRequest, LeadCreate, LeadDetail, LeadOut
from app.services import event, latest_analysis, process_lead
from app.integrations.orchestrator import integration_health
from app.integrations.factory import get_email_provider
logging.basicConfig(level=logging.INFO)
logger=logging.getLogger("leadflow")
@asynccontextmanager
async def app_lifespan(_app):
 if settings.workspace_auth_enabled and not all((settings.session_secret_key, settings.admin_email, settings.admin_password)):
  raise RuntimeError("SESSION_SECRET_KEY, ADMIN_EMAIL, and ADMIN_PASSWORD are required when workspace authentication is enabled")
 yield

app=FastAPI(title="NEXORA AI — Nexora LeadFlow",version="1.0.0",description="Human-reviewed inbound lead qualification and response drafting.",lifespan=app_lifespan)
app.add_middleware(
 SignedSessionMiddleware,
 secret_key=settings.session_secret_key or "development-only-session-secret-change-before-deploying",
 same_site="strict",
 https_only=settings.app_env.lower() in {"production", "prod"},
 max_age=8 * 60 * 60,
)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=False, allow_methods=["GET","POST"], allow_headers=["Content-Type"])
@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    logger.error("unhandled_request_error", extra={"path": request.url.path, "error_type": type(exc).__name__})
    return JSONResponse(status_code=500, content={"detail": "Unexpected server error"})

app.mount("/static",StaticFiles(directory="app/static"),name="static")
templates=Jinja2Templates(directory="app/templates")
def require_workspace(request: Request):
 if settings.workspace_auth_enabled and not request.session.get("authenticated"):
  raise HTTPException(status_code=401, detail="Workspace sign-in required")

def out(l): return {"id":l.id,"name":l.name,"email":l.email,"company":l.company,"website":l.website,"industry":l.industry,"budget":l.budget,"timeline":l.timeline,"message":l.message,"created_at":l.created_at,"updated_at":l.updated_at,"latest_analysis":latest_analysis(l)}
@app.get("/",response_class=HTMLResponse,include_in_schema=False)
def dashboard(request:Request):
 if settings.workspace_auth_enabled and not request.session.get("authenticated"):
  return RedirectResponse("/signin", status_code=303)
 return templates.TemplateResponse(request,"dashboard.html", {"demo_mode": False, "auth_enabled": settings.workspace_auth_enabled})
@app.get("/demo", response_class=HTMLResponse, include_in_schema=False)
def demo(request: Request): return templates.TemplateResponse(request, "dashboard.html", {"demo_mode": True})
@app.get("/request", response_class=HTMLResponse, include_in_schema=False)
def request_form(request: Request):
 return templates.TemplateResponse(request, "request.html", {"errors": [], "values": {}})
@app.post("/request", response_class=HTMLResponse, include_in_schema=False)
async def submit_request(request: Request, db: Session = Depends(get_db)):
 form = await request.form()
 # A quiet honeypot absorbs basic scripted submissions without exposing lead data.
 if form.get("middle_name"):
  return RedirectResponse("/request/thanks", status_code=303)
 values = {key: (str(form.get(key, "")).strip() or None) for key in
           ("name", "email", "company", "website", "industry", "budget", "timeline", "message")}
 if form.get("consent") != "yes":
  return templates.TemplateResponse(request, "request.html", {
   "errors": ["Please confirm that our team may contact you about this request."], "values": values,
  }, status_code=422)
 try:
  payload = LeadCreate.model_validate(values)
 except ValidationError:
  messages = ["Please check the required fields and email address, then try again."]
  return templates.TemplateResponse(request, "request.html", {"errors": messages, "values": values}, status_code=422)
 try:
  _save_lead(payload, db, source="public_request_form", consent_to_contact=True)
 except HTTPException:
  return templates.TemplateResponse(request, "request.html", {
   "errors": ["We couldn't submit your request right now. Please try again shortly."], "values": values,
  }, status_code=503)
 return RedirectResponse("/request/thanks", status_code=303)
@app.get("/request/thanks", response_class=HTMLResponse, include_in_schema=False)
def request_thanks(request: Request): return templates.TemplateResponse(request, "request_thanks.html")
@app.get("/signin", response_class=HTMLResponse, include_in_schema=False)
def signin(request: Request):
 if settings.workspace_auth_enabled and request.session.get("authenticated"):
  return RedirectResponse("/", status_code=303)
 return templates.TemplateResponse(request, "signin.html", {"auth_enabled": settings.workspace_auth_enabled, "error": None})
@app.post("/signin", response_class=HTMLResponse, include_in_schema=False)
def signin_submit(request: Request, email: str = Form(...), password: str = Form(...)):
 if not settings.workspace_auth_enabled:
  return RedirectResponse("/demo", status_code=303)
 email_ok = bool(settings.admin_email) and hmac.compare_digest(email.strip().casefold(), settings.admin_email.strip().casefold())
 password_ok = bool(settings.admin_password) and hmac.compare_digest(password, settings.admin_password)
 if not (email_ok and password_ok):
  return templates.TemplateResponse(request, "signin.html", {"auth_enabled": True, "error": "Email or password is incorrect."}, status_code=401)
 request.session.clear()
 request.session["authenticated"] = True
 return RedirectResponse("/", status_code=303)
@app.post("/logout", include_in_schema=False)
def logout(request: Request):
 request.session.clear()
 return RedirectResponse("/signin", status_code=303)
@app.get("/api/health")
def health(db:Session=Depends(get_db)):
 try: db.execute(select(1)); return {"status":"ok","database":"connected","integrations":integration_health()}
 except Exception as e: raise HTTPException(503,"Database unavailable") from e
def _save_lead(p: LeadCreate, db: Session, *, source: str, consent_to_contact: bool = False) -> Lead:
 l=Lead(**p.model_dump()); l.website=str(l.website) if l.website else None; db.add(l)
 try:
  db.flush()
  details = {"source": source}
  if consent_to_contact:
   details["consent_to_contact"] = True
  event(db,l.id,"LEAD_RECEIVED",details); db.commit(); db.refresh(l)
 except Exception as e:
  db.rollback(); logger.error("lead_persistence_failed", extra={"error_type": type(e).__name__})
  raise HTTPException(503,"Lead could not be saved") from e
 try: process_lead(db,l)
 except Exception: logger.warning("lead_saved_without_analysis",extra={"lead_id":l.id})
 db.refresh(l)
 return l
@app.post("/api/leads",response_model=LeadOut,status_code=201)
def create_lead(p:LeadCreate,db:Session=Depends(get_db),_=Depends(require_workspace)):
 return out(_save_lead(p, db, source="dashboard_or_api"))
@app.get("/api/leads",response_model=list[LeadOut])
def list_leads(limit:int=100,offset:int=0,db:Session=Depends(get_db),_ = Depends(require_workspace)):
 if not 1<=limit<=500 or offset<0: raise HTTPException(422,"Invalid pagination parameters")
 rows=db.scalars(select(Lead).options(selectinload(Lead.analyses)).order_by(Lead.created_at.desc()).limit(limit).offset(offset)).all()
 return [out(x) for x in rows]
@app.get("/api/leads/{lead_id}",response_model=LeadDetail)
def get_lead(lead_id:int,db:Session=Depends(get_db),_ = Depends(require_workspace)):
 l=db.scalar(select(Lead).where(Lead.id==lead_id).options(selectinload(Lead.analyses),selectinload(Lead.events)))
 if not l: raise HTTPException(404,"Lead not found")
 r=out(l); r["events"]=sorted(l.events,key=lambda x:x.created_at); return r
@app.post("/api/leads/{lead_id}/reanalyze",response_model=LeadOut)
def reanalyze(lead_id:int,db:Session=Depends(get_db),_ = Depends(require_workspace)):
 l=db.scalar(select(Lead).where(Lead.id==lead_id).options(selectinload(Lead.analyses)))
 if not l: raise HTTPException(404,"Lead not found")
 try: process_lead(db,l)
 except Exception as e: raise HTTPException(503,"Analysis unavailable; lead remains unclassified") from e
 db.refresh(l); return out(l)
@app.get("/api/dashboard/summary",response_model=DashboardSummary)
def summary(db:Session=Depends(get_db),_ = Depends(require_workspace)):
 total=db.scalar(select(func.count(Lead.id))) or 0
 ids=select(func.max(LeadAnalysis.id).label("analysis_id")).group_by(LeadAnalysis.lead_id).subquery()
 last=select(LeadAnalysis).join(ids,LeadAnalysis.id==ids.c.analysis_id).subquery()
 c={s:db.scalar(select(func.count()).select_from(last).where(last.c.lead_status==s)) or 0 for s in ("HOT","WARM","NURTURE")}
 review=db.scalar(select(func.count()).select_from(last).where(last.c.human_review.is_(True))) or 0
 due=db.scalar(select(func.count(FollowUp.id)).where(FollowUp.status=="PENDING",FollowUp.scheduled_at<=datetime.now(timezone.utc))) or 0
 return DashboardSummary(total_leads=total,hot_leads=c["HOT"],warm_leads=c["WARM"],nurture_leads=c["NURTURE"],human_review_required=review,follow_ups_due=due)
@app.post("/api/leads/{lead_id}/review")
def decide(lead_id:int,p:DecisionRequest,db:Session=Depends(get_db),_ = Depends(require_workspace)):
 l=db.scalar(select(Lead).where(Lead.id==lead_id).options(selectinload(Lead.analyses)))
 if not l: raise HTTPException(404,"Lead not found")
 a=latest_analysis(l)
 if not a: raise HTTPException(409,"Lead has no analysis to review")
 if p.decision=="RECLASSIFY" and not p.new_status: raise HTTPException(422,"new_status is required")
 if p.decision=="RECLASSIFY": a.lead_status=p.new_status.value
 if p.decision in ("APPROVE","REQUEST_INFORMATION","RECLASSIFY"): a.human_review=False; a.review_reason=None
 elif p.decision=="REJECT": a.human_review=True; a.review_reason=p.notes or "Reviewer rejected this recommendation."
 if p.decision=="REQUEST_INFORMATION": a.recommended_action="REQUEST_INFORMATION"
 event(db,lead_id,"HUMAN_DECISION",{"decision":p.decision,"notes":p.notes,"new_status":p.new_status.value if p.new_status else None})
 if p.decision == "REJECT":
  event(db,lead_id,"EMAIL_APPROVAL_REJECTED",{"analysis_id":a.id})
  event(db,lead_id,"EMAIL_SEND_SKIPPED",{"analysis_id":a.id,"reason":"rejected"})
 elif p.decision == "REQUEST_INFORMATION":
  event(db,lead_id,"EMAIL_APPROVAL_INFORMATION_REQUESTED",{"analysis_id":a.id})
  event(db,lead_id,"EMAIL_SEND_SKIPPED",{"analysis_id":a.id,"reason":"information_requested"})
 elif p.decision == "RECLASSIFY":
  event(db,lead_id,"EMAIL_SEND_SKIPPED",{"analysis_id":a.id,"reason":"reclassified_requires_approval"})
 db.commit()
 return {"ok":True,"analysis":a}


@app.post("/api/leads/{lead_id}/approve")
def approve_and_send(lead_id: int, db: Session = Depends(get_db), _ = Depends(require_workspace)):
 # A row lock serializes approval attempts on PostgreSQL. The started event is
 # committed before the provider call, preventing concurrent duplicate sends.
 lead = db.scalar(select(Lead).where(Lead.id == lead_id).with_for_update())
 if not lead:
  raise HTTPException(404, "Lead not found")
 analysis = latest_analysis(lead)
 if not analysis:
  raise HTTPException(409, "Lead has no analysis to approve")
 if not analysis.response_draft or not analysis.response_draft.strip():
  raise HTTPException(409, "Lead has no response draft to send")
 if analysis.lead_status == "UNQUALIFIED":
  raise HTTPException(409, "This lead is not eligible for email approval")

 prior_events = db.scalars(select(WorkflowEvent).where(
  WorkflowEvent.lead_id == lead_id,
  WorkflowEvent.event_type.in_(("EMAIL_SENT", "EMAIL_SEND_STARTED", "EMAIL_SEND_FAILED")),
 ).order_by(WorkflowEvent.id)).all()
 current_events = [e for e in prior_events if e.event_data.get("analysis_id") == analysis.id]
 last_started = max((e.id for e in current_events if e.event_type == "EMAIL_SEND_STARTED"), default=0)
 last_failure = max((e.id for e in current_events if e.event_type == "EMAIL_SEND_FAILED"), default=0)
 if any(e.event_type == "EMAIL_SENT" for e in current_events):
  return {"status": "already_sent", "provider": next(e.event_data.get("provider") for e in reversed(current_events) if e.event_type == "EMAIL_SENT")}
 if last_started > last_failure:
  raise HTTPException(409, "Email send is already in progress")

 provider = get_email_provider()
 if provider.mode == "disabled":
  event(db, lead_id, "HUMAN_DECISION", {"decision": "APPROVE", "action": "APPROVE_AND_SEND", "analysis_id": analysis.id})
  event(db, lead_id, "EMAIL_APPROVAL_GRANTED", {"analysis_id": analysis.id})
  event(db, lead_id, "EMAIL_SEND_SKIPPED", {"analysis_id": analysis.id, "reason": "disabled"})
  db.commit()
  raise HTTPException(409, "Email sending is disabled")

 subject = f"Following up on your inquiry{f' about {lead.company}' if lead.company else ''}"
 recipient_domain = lead.email.rsplit("@", 1)[-1].lower()
 event(db, lead_id, "HUMAN_DECISION", {"decision": "APPROVE", "action": "APPROVE_AND_SEND", "analysis_id": analysis.id})
 event(db, lead_id, "EMAIL_APPROVAL_GRANTED", {"analysis_id": analysis.id})
 event(db, lead_id, "EMAIL_SEND_STARTED", {"analysis_id": analysis.id, "provider": provider.mode,
                                              "recipient_domain": recipient_domain})
 db.commit()
 try:
  result = provider.send_email(lead.email, subject, analysis.response_draft, lead.id, analysis.id)
  category = result.error_category
  success = result.success
 except Exception as exc:
  logger.warning("email_send_failed error_type=%s", type(exc).__name__)
  category = type(exc).__name__
  success = False
  result = None

 if success:
  event(db, lead_id, "EMAIL_SENT", {"analysis_id": analysis.id, "provider": result.provider,
                                    "status": result.status, "message_id": result.message_id,
                                    "recipient_domain": recipient_domain})
  db.commit()
  return {"status": "sent", "provider": result.provider, "message_id": result.message_id}

 safe_category = category if category and len(category) <= 40 and category.replace("_", "").isalnum() else "send_failed"
 logger.warning("email_send_failed category=%s", safe_category)
 event(db, lead_id, "EMAIL_SEND_FAILED", {"analysis_id": analysis.id, "provider": result.provider if result else provider.mode,
                                           "error_category": safe_category, "recipient_domain": recipient_domain})
 db.commit()
 raise HTTPException(502, f"Email send failed ({safe_category})")

