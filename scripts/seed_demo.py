"""Seed the documented example lead and run its standard workflow once."""
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Lead
from app.services import event, process_lead

def main():
    with SessionLocal() as db:
        lead = db.scalar(select(Lead).where(Lead.email == "sarah.johnson@fintechpro.example"))
        if lead is None:
            lead = Lead(
                name="Sarah Johnson",
                email="sarah.johnson@fintechpro.example",
                company="FinTechPro",
                industry="Fintech",
                budget="$5,000-$10,000/month",
                timeline="Launching within 30 days",
                message="We are launching a new fintech product and need help with paid advertising and LinkedIn lead generation. We want to start campaigns within the next month and would like to understand how your agency can help.",
            )
            db.add(lead)
            db.flush()
            event(db, lead.id, "LEAD_RECEIVED", {"source": "demo_seed"})
            db.commit()
        if not lead.analyses:
            try:
                process_lead(db, lead)
            except Exception:
                print("Demo lead saved without classification. Configure OPENAI_API_KEY and retry in the dashboard.")
        print(f"Demo lead id: {lead.id}")

if __name__ == "__main__":
    main()