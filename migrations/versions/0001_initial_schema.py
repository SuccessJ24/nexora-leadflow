"""Create the initial, versioned LeadFlow schema."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("company", sa.String(length=200), nullable=True),
        sa.Column("website", sa.String(length=500), nullable=True),
        sa.Column("industry", sa.String(length=120), nullable=True),
        sa.Column("budget", sa.String(length=120), nullable=True),
        sa.Column("timeline", sa.String(length=200), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_leads_email", "leads", ["email"])
    op.create_index("ix_leads_created_at", "leads", ["created_at"])
    op.create_table(
        "lead_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lead_status", sa.String(length=20), nullable=False),
        sa.Column("service_fit", sa.String(length=20), nullable=False),
        sa.Column("intent", sa.String(length=20), nullable=False),
        sa.Column("urgency", sa.String(length=20), nullable=False),
        sa.Column("budget_fit", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("pain_points", sa.JSON(), nullable=False),
        sa.Column("requested_services", sa.JSON(), nullable=False),
        sa.Column("missing_information", sa.JSON(), nullable=False),
        sa.Column("recommended_action", sa.String(length=30), nullable=False),
        sa.Column("human_review", sa.Boolean(), nullable=False),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("response_draft", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_analysis_confidence_range"),
    )
    op.create_index("ix_lead_analyses_lead_id", "lead_analyses", ["lead_id"])
    op.create_index("ix_lead_analyses_lead_status", "lead_analyses", ["lead_status"])
    op.create_index("ix_analyses_status_review", "lead_analyses", ["lead_status", "human_review"])
    op.create_table(
        "follow_ups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_follow_ups_lead_id", "follow_ups", ["lead_id"])
    op.create_index("ix_follow_ups_scheduled_at", "follow_ups", ["scheduled_at"])
    op.create_index("ix_follow_ups_status", "follow_ups", ["status"])
    op.create_table(
        "workflow_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("event_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workflow_events_lead_id", "workflow_events", ["lead_id"])
    op.create_index("ix_workflow_events_event_type", "workflow_events", ["event_type"])
    op.create_index("ix_workflow_events_created_at", "workflow_events", ["created_at"])

def downgrade():
    op.drop_table("workflow_events")
    op.drop_table("follow_ups")
    op.drop_table("lead_analyses")
    op.drop_table("leads")