"""Phase two snapshots and explicit workflow states; no financial or AI facts."""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import Identity, now


class Versioned:
    row_version: Mapped[int] = mapped_column(Integer, default=1)


class Approval(Versioned):
    editor_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    created_by: Mapped[str] = mapped_column(String(80))
    approved_by: Mapped[str | None] = mapped_column(String(80))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_ref: Mapped[str | None] = mapped_column(String(500))
    source_ref: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ActionTemplate(Identity, Approval, Base):
    __tablename__ = "action_template_versions"
    __table_args__ = (
        UniqueConstraint("template_code", "version_label"),
        Index(
            "uq_approved_template",
            "template_code",
            unique=True,
            sqlite_where=text("status = 'approved'"),
            postgresql_where=text("status = 'approved'"),
        ),
        CheckConstraint("status IN ('draft','pending_review','approved','retired')"),
    )
    template_code: Mapped[str] = mapped_column(String(64))
    version_label: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    node_type_code: Mapped[str] = mapped_column(ForeignKey("node_types.code"))
    applicability_json: Mapped[dict] = mapped_column(JSON, default=dict)
    __mapper_args__ = {"version_id_col": Approval.row_version}


class ActionItem(Identity, Base):
    __tablename__ = "action_template_items"
    __table_args__ = (UniqueConstraint("template_version_id", "item_code"),)
    template_version_id: Mapped[str] = mapped_column(ForeignKey("action_template_versions.id"))
    item_code: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(240))
    materials_required_json: Mapped[list] = mapped_column(JSON, default=list)
    default_department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"))
    completion_criteria: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ActionLink(Identity, Base):
    __tablename__ = "milestone_action_links"
    __table_args__ = (
        UniqueConstraint("plan_item_id", "template_item_id"),
        CheckConstraint("status IN ('active','superseded','cancelled')"),
    )
    milestone_id: Mapped[str] = mapped_column(ForeignKey("milestones.id"), index=True)
    plan_item_id: Mapped[str] = mapped_column(ForeignKey("milestone_plan_items.id"), index=True)
    template_item_id: Mapped[str] = mapped_column(ForeignKey("action_template_items.id"))
    assigned_department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"))
    snapshot_json: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkCalendar(Identity, Approval, Base):
    __tablename__ = "work_calendars"
    __table_args__ = (
        UniqueConstraint("calendar_code", "version_label"),
        Index(
            "uq_approved_calendar",
            "calendar_code",
            unique=True,
            sqlite_where=text("status = 'approved'"),
            postgresql_where=text("status = 'approved'"),
        ),
        CheckConstraint("status IN ('draft','pending_review','approved','retired')"),
        CheckConstraint("end_date >= start_date"),
    )
    calendar_code: Mapped[str] = mapped_column(String(64))
    version_label: Mapped[str] = mapped_column(String(30))
    timezone_name: Mapped[str] = mapped_column(String(50))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    __mapper_args__ = {"version_id_col": Approval.row_version}


class CalendarDay(Identity, Base):
    __tablename__ = "work_calendar_days"
    __table_args__ = (UniqueConstraint("calendar_id", "calendar_date"),)
    calendar_id: Mapped[str] = mapped_column(ForeignKey("work_calendars.id"))
    calendar_date: Mapped[date] = mapped_column(Date)
    is_workday: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(String(160), default="")


class ReminderRule(Identity, Approval, Base):
    __tablename__ = "reminder_rule_versions"
    __table_args__ = (
        UniqueConstraint("rule_code", "version_label"),
        Index(
            "uq_approved_rule",
            "rule_code",
            unique=True,
            sqlite_where=text("status = 'approved'"),
            postgresql_where=text("status = 'approved'"),
        ),
        CheckConstraint("status IN ('draft','pending_review','approved','retired')"),
        CheckConstraint("day_basis IN ('calendar_day','workday')"),
        CheckConstraint("days_before >= 0 AND days_before <= 365"),
        CheckConstraint("catch_up_days >= 0 AND catch_up_days <= 365"),
        CheckConstraint("day_basis != 'workday' OR calendar_id IS NOT NULL"),
        CheckConstraint("recipient_role_code IN ('admin','editor','reviewer','viewer')"),
    )
    rule_code: Mapped[str] = mapped_column(String(64))
    version_label: Mapped[str] = mapped_column(String(30))
    node_type_code: Mapped[str] = mapped_column(ForeignKey("node_types.code"))
    days_before: Mapped[int] = mapped_column(Integer)
    day_basis: Mapped[str] = mapped_column(String(20))
    calendar_id: Mapped[str | None] = mapped_column(ForeignKey("work_calendars.id"))
    recipient_role_code: Mapped[str] = mapped_column(String(30))
    catch_up_days: Mapped[int] = mapped_column(Integer, default=0)
    __mapper_args__ = {"version_id_col": Approval.row_version}


class Reminder(Identity, Base):
    __tablename__ = "reminder_instances"
    __table_args__ = (CheckConstraint("status IN ('draft_created','invalidated')"),)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    milestone_plan_item_id: Mapped[str] = mapped_column(ForeignKey("milestone_plan_items.id"))
    rule_version_id: Mapped[str] = mapped_column(ForeignKey("reminder_rule_versions.id"))
    recipient_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    trigger_date: Mapped[date] = mapped_column(Date, index=True)
    occurrence_no: Mapped[int] = mapped_column(Integer, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="draft_created")
    invalidated_reason: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Notification(Identity, Versioned, Base):
    __tablename__ = "notification_drafts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','pending_review','returned','approved_pending_send','sent','invalidated')"
        ),
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    reminder_instance_id: Mapped[str] = mapped_column(
        ForeignKey("reminder_instances.id"), unique=True
    )
    recipient_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    draft_version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    fact_snapshot_json: Mapped[dict] = mapped_column(JSON)
    editor_ids: Mapped[list] = mapped_column(JSON, default=list)
    submitted_by: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __mapper_args__ = {"version_id_col": Versioned.row_version}


class NotificationReview(Identity, Base):
    __tablename__ = "notification_reviews"
    notification_id: Mapped[str] = mapped_column(ForeignKey("notification_drafts.id"), index=True)
    draft_version: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(30))
    comment: Mapped[str] = mapped_column(Text)
    reviewer_id: Mapped[str] = mapped_column(String(80))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DeliveryAttempt(Identity, Base):
    __tablename__ = "notification_delivery_attempts"
    __table_args__ = (UniqueConstraint("notification_id", "attempt_no"),)
    notification_id: Mapped[str] = mapped_column(ForeignKey("notification_drafts.id"))
    channel: Mapped[str] = mapped_column(String(40))
    destination_ref: Mapped[str] = mapped_column(String(80))
    attempt_state: Mapped[str] = mapped_column(String(30))
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    failure_reason: Mapped[str | None] = mapped_column(Text)


class InboxMessage(Identity, Base):
    __tablename__ = "inbox_messages"
    notification_id: Mapped[str] = mapped_column(ForeignKey("notification_drafts.id"), unique=True)
    recipient_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Task(Identity, Versioned, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("milestone_action_link_id", "rule_version_id"),
        CheckConstraint(
            "status IN ('unassigned','todo','in_progress','submitted','verified_done','returned','cancelled')"
        ),
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    reminder_instance_id: Mapped[str] = mapped_column(ForeignKey("reminder_instances.id"))
    milestone_action_link_id: Mapped[str] = mapped_column(ForeignKey("milestone_action_links.id"))
    rule_version_id: Mapped[str] = mapped_column(ForeignKey("reminder_rule_versions.id"))
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    due_date: Mapped[date] = mapped_column(Date)
    title: Mapped[str] = mapped_column(String(240))
    action_snapshot_json: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="unassigned", index=True)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __mapper_args__ = {"version_id_col": Versioned.row_version}


class Feedback(Identity, Base):
    __tablename__ = "task_feedback"
    __table_args__ = (CheckConstraint("status IN ('submitted','verified','returned','disputed')"),)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    comment: Mapped[str] = mapped_column(Text)
    claimed_completion: Mapped[bool] = mapped_column(Boolean)
    evidence_ref: Mapped[str] = mapped_column(String(500))
    submitted_by: Mapped[str] = mapped_column(String(80))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    status: Mapped[str] = mapped_column(String(30), default="submitted")


class TaskVerification(Identity, Base):
    __tablename__ = "task_verifications"
    feedback_id: Mapped[str] = mapped_column(ForeignKey("task_feedback.id"), unique=True)
    decision: Mapped[str] = mapped_column(String(30))
    comment: Mapped[str] = mapped_column(Text)
    reviewer_id: Mapped[str] = mapped_column(String(80))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
