from datetime import date, datetime, timezone
from uuid import uuid4

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
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc)


class Identity:
    id: Mapped[str] = mapped_column(
        String(36).with_variant(Uuid(as_uuid=False), "postgresql"), primary_key=True, default=uid
    )


class Department(Identity, Base):
    __tablename__ = "departments"
    dept_code: Mapped[str] = mapped_column(String(40), unique=True)
    dept_name: Mapped[str] = mapped_column(String(100), unique=True)


class User(Identity, Base):
    __tablename__ = "users"
    employee_code: Mapped[str] = mapped_column(String(50), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"))


class Credential(Identity, Base):
    __tablename__ = "auth_credentials"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_system_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(Identity, Base):
    __tablename__ = "auth_sessions"
    credential_id: Mapped[str] = mapped_column(ForeignKey("auth_credentials.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(80))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ProjectMember(Identity, Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", "role_code"),
        CheckConstraint("role_code IN ('admin','editor','reviewer','viewer')"),
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role_code: Mapped[str] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class NodeType(Base):
    __tablename__ = "node_types"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Project(Identity, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "project_status IN ('draft','not_started','active','completed','archived')"
        ),
        CheckConstraint(
            "planned_end IS NULL OR planned_start IS NULL OR planned_end >= planned_start"
        ),
        Index("ix_projects_status_type", "project_status", "project_type"),
    )
    project_code: Mapped[str] = mapped_column(String(64), unique=True)
    project_name: Mapped[str] = mapped_column(String(200))
    project_type: Mapped[str | None] = mapped_column(String(60))
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"))
    project_status: Mapped[str] = mapped_column(String(30), default="not_started")
    attention_note: Mapped[str | None] = mapped_column(Text)
    planned_start: Mapped[date | None] = mapped_column(Date)
    planned_end: Mapped[date | None] = mapped_column(Date)
    current_plan_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_plan_versions.id", use_alter=True, name="fk_current_plan")
    )
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    created_by: Mapped[str] = mapped_column(String(80), default="system")
    data_source: Mapped[str] = mapped_column(String(30), default="manual_demo")
    __mapper_args__ = {"version_id_col": row_version}


class PlanVersion(Identity, Base):
    __tablename__ = "project_plan_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_label"),
        CheckConstraint("status IN ('draft','effective','superseded')"),
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    version_label: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    change_reason: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str | None] = mapped_column(String(500))
    base_version_id: Mapped[str | None] = mapped_column(ForeignKey("project_plan_versions.id"))
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    editor_ids: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    approved_by: Mapped[str | None] = mapped_column(String(80))
    approval_ref: Mapped[str | None] = mapped_column(String(500))
    __mapper_args__ = {"version_id_col": row_version}


class Milestone(Identity, Base):
    __tablename__ = "milestones"
    __table_args__ = (UniqueConstraint("project_id", "milestone_code"),)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    milestone_code: Mapped[str] = mapped_column(String(64))
    milestone_name: Mapped[str] = mapped_column(String(200))
    node_type_code: Mapped[str] = mapped_column(ForeignKey("node_types.code"))
    lifecycle_status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": row_version}


class PlanItem(Identity, Base):
    __tablename__ = "milestone_plan_items"
    __table_args__ = (
        UniqueConstraint("milestone_id", "plan_version_id"),
        CheckConstraint("date_kind IN ('contractual','internal_plan','unconfirmed')"),
    )
    milestone_id: Mapped[str] = mapped_column(ForeignKey("milestones.id"), index=True)
    plan_version_id: Mapped[str] = mapped_column(ForeignKey("project_plan_versions.id"), index=True)
    # Name and type are snapshotted too, so historical screens never change retrospectively.
    milestone_name: Mapped[str] = mapped_column(String(200))
    node_type_code: Mapped[str] = mapped_column(ForeignKey("node_types.code"))
    planned_date: Mapped[date] = mapped_column(Date)
    date_kind: Mapped[str] = mapped_column(String(30), default="internal_plan")
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"))
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    source_ref: Mapped[str | None] = mapped_column(String(500))
    change_reason: Mapped[str] = mapped_column(Text)
    is_included: Mapped[bool] = mapped_column(Boolean, default=True)


class ActualRecord(Identity, Base):
    __tablename__ = "milestone_actual_records"
    __table_args__ = (
        CheckConstraint("verification_status IN ('submitted','verified','returned','disputed')"),
        CheckConstraint("completion_flag IS NOT TRUE OR actual_date IS NOT NULL"),
        CheckConstraint(
            "actual_date IS NULL OR completion_flag IS TRUE",
            name="ck_actual_date_requires_completion",
        ),
        Index(
            "uq_current_actual",
            "milestone_id",
            unique=True,
            sqlite_where=text("is_current = true"),
            postgresql_where=text("is_current = true"),
        ),
    )
    milestone_id: Mapped[str] = mapped_column(ForeignKey("milestones.id"), index=True)
    actual_date: Mapped[date | None] = mapped_column(Date)
    completion_flag: Mapped[bool | None] = mapped_column(Boolean)
    verification_status: Mapped[str] = mapped_column(String(30), default="submitted")
    evidence_ref: Mapped[str] = mapped_column(String(500))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    submitted_by: Mapped[str] = mapped_column(String(80), default="system")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[str | None] = mapped_column(String(80))
    comment: Mapped[str | None] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditEvent(Identity, Base):
    __tablename__ = "audit_events"
    aggregate_type: Mapped[str] = mapped_column(String(50))
    aggregate_id: Mapped[str] = mapped_column(
        String(36).with_variant(Uuid(as_uuid=False), "postgresql"), index=True
    )
    action: Mapped[str] = mapped_column(String(80))
    before_json: Mapped[dict | None] = mapped_column(JSON)
    after_json: Mapped[dict | None] = mapped_column(JSON)
    actor_id: Mapped[str] = mapped_column(String(80), default="system")
    request_id: Mapped[str] = mapped_column(String(80))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ImportBatch(Identity, Base):
    __tablename__ = "import_batches"
    target_entity: Mapped[str] = mapped_column(String(35))
    filename: Mapped[str] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64))
    mapping_json: Mapped[dict] = mapped_column(JSON)
    context_json: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="validated")
    preview_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(160), unique=True)
    commit_payload_hash: Mapped[str | None] = mapped_column(String(64))
    result_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(
        String(80), default="legacy-unassigned", server_default="legacy-unassigned"
    )
    __mapper_args__ = {"version_id_col": row_version}


class ImportRow(Identity, Base):
    __tablename__ = "import_rows"
    __table_args__ = (UniqueConstraint("batch_id", "sheet_name", "source_row_number"),)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"), index=True)
    sheet_name: Mapped[str] = mapped_column(String(80))
    source_row_number: Mapped[int] = mapped_column(Integer)
    raw_json: Mapped[dict] = mapped_column(JSON)
    normalized_json: Mapped[dict | None] = mapped_column(JSON)
    validation_errors_json: Mapped[list] = mapped_column(JSON, default=list)
    row_status: Mapped[str] = mapped_column(String(30))
    target_record_id: Mapped[str | None] = mapped_column(
        String(36).with_variant(Uuid(as_uuid=False), "postgresql")
    )
