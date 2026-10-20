"""Frozen evaluation evidence, restricted finance facts and independently reviewed reports."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import Identity, now


class FinancialAccess(Identity, Base):
    __tablename__ = "financial_access"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id"),
        CheckConstraint("can_write IS NOT TRUE OR can_read IS TRUE"),
        CheckConstraint("can_verify IS NOT TRUE OR can_read IS TRUE"),
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    can_read: Mapped[bool] = mapped_column(Boolean, default=False)
    can_write: Mapped[bool] = mapped_column(Boolean, default=False)
    can_verify: Mapped[bool] = mapped_column(Boolean, default=False)


class FinancialPlan(Identity, Base):
    __tablename__ = "financial_plans"
    __table_args__ = (
        UniqueConstraint("project_id", "record_code"),
        CheckConstraint("direction IN ('receivable','payable')"),
        CheckConstraint("planned_amount > 0"),
        CheckConstraint("date_source_kind IN ('contractual','internal_plan','unconfirmed')"),
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    milestone_id: Mapped[str | None] = mapped_column(ForeignKey("milestones.id"))
    record_code: Mapped[str] = mapped_column(String(64))
    direction: Mapped[str] = mapped_column(String(20))
    planned_date: Mapped[date] = mapped_column(Date)
    planned_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    date_source_kind: Mapped[str] = mapped_column(String(30))
    source_ref: Mapped[str] = mapped_column(String(500))
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class FinancialActual(Identity, Base):
    __tablename__ = "financial_actuals"
    __table_args__ = (
        UniqueConstraint("project_id", "record_code"),
        CheckConstraint("direction IN ('receipt','payment')"),
        CheckConstraint("actual_amount > 0"),
        CheckConstraint("verification_status IN ('submitted','verified','returned','disputed')"),
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    financial_plan_id: Mapped[str | None] = mapped_column(ForeignKey("financial_plans.id"))
    record_code: Mapped[str] = mapped_column(String(64))
    direction: Mapped[str] = mapped_column(String(20))
    actual_date: Mapped[date] = mapped_column(Date)
    actual_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    evidence_ref: Mapped[str] = mapped_column(String(500))
    submitted_by: Mapped[str] = mapped_column(String(80))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    verification_status: Mapped[str] = mapped_column(String(30), default="submitted")
    verified_by: Mapped[str | None] = mapped_column(String(80))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": row_version}


class MetricSnapshot(Identity, Base):
    __tablename__ = "metric_snapshots"
    __table_args__ = (UniqueConstraint("project_id", "source_digest"),)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    plan_version_id: Mapped[str] = mapped_column(ForeignKey("project_plan_versions.id"))
    formula_version: Mapped[str] = mapped_column(String(50))
    source_digest: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReportDraft(Identity, Base):
    __tablename__ = "report_drafts"
    __table_args__ = (
        UniqueConstraint("project_id", "request_key"),
        CheckConstraint("review_status IN ('draft','pending_review','returned','approved')"),
        CheckConstraint("generator_type IN ('mock','llm_assisted')"),
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    metric_snapshot_id: Mapped[str] = mapped_column(ForeignKey("metric_snapshots.id"))
    request_key: Mapped[str] = mapped_column(String(160))
    request_digest: Mapped[str] = mapped_column(String(64))
    report_type: Mapped[str] = mapped_column(String(30))
    fact_bundle_json: Mapped[dict] = mapped_column(JSON)
    generator_type: Mapped[str] = mapped_column(String(25))
    model_id: Mapped[str | None] = mapped_column(String(256))
    content: Mapped[str] = mapped_column(Text)
    validation_json: Mapped[dict] = mapped_column(JSON)
    contains_finance: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(String(30), default="draft")
    created_by: Mapped[str] = mapped_column(String(80))
    editor_ids: Mapped[list] = mapped_column(JSON, default=list)
    reviewer_id: Mapped[str | None] = mapped_column(String(80))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": row_version}


class ReportReview(Identity, Base):
    __tablename__ = "report_reviews"
    report_id: Mapped[str] = mapped_column(ForeignKey("report_drafts.id"), index=True)
    decision: Mapped[str] = mapped_column(String(30))
    comment: Mapped[str] = mapped_column(Text)
    reviewer_id: Mapped[str] = mapped_column(String(80))
    content_digest: Mapped[str] = mapped_column(String(64))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
