"""Persisted model configuration. Selection FKs cannot reference disabled models."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import Identity, now

SERVICE_ID = "00000000-0000-0000-0000-000000000100"
DEFAULT_BASE_URL = "https://maas-api.cmhk.com/v1"


class LLMConfig(Identity, Base):
    __tablename__ = "llm_service_config"
    __table_args__ = (
        CheckConstraint(f"id = '{SERVICE_ID}'"),
        CheckConstraint("adapter = 'openai_compatible'"),
        CheckConstraint("mode IN ('mock','maas')"),
        CheckConstraint("timeout_seconds BETWEEN 1 AND 60"),
    )
    service_name: Mapped[str] = mapped_column(String(120))
    base_url: Mapped[str] = mapped_column(String(500))
    adapter: Mapped[str] = mapped_column(String(40), default="openai_compatible")
    mode: Mapped[str] = mapped_column(String(20), default="mock")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=20)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    credential_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    endpoint_revision: Mapped[int] = mapped_column(Integer, default=1)
    last_connection_test: Mapped[dict | None] = mapped_column(JSON)
    last_models_refresh: Mapped[dict | None] = mapped_column(JSON)
    updated_by: Mapped[str] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": row_version}


class LLMModel(Identity, Base):
    __tablename__ = "llm_models"
    __table_args__ = (
        UniqueConstraint("service_id", "endpoint_revision", "model_id"),
        UniqueConstraint("service_id", "id", "enabled"),
        CheckConstraint("source IN ('discovered','manual')"),
        CheckConstraint("verification_status IN ('untested','available','failed')"),
    )
    service_id: Mapped[str] = mapped_column(ForeignKey("llm_service_config.id"))
    endpoint_revision: Mapped[int] = mapped_column(Integer)
    model_id: Mapped[str] = mapped_column(String(256))
    display_name: Mapped[str] = mapped_column(String(256))
    source: Mapped[str] = mapped_column(String(20))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    verification_status: Mapped[str] = mapped_column(String(20), default="untested")
    tested_revision: Mapped[int | None] = mapped_column(Integer)
    last_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_result: Mapped[dict | None] = mapped_column(JSON)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": row_version}


class LLMSelection(Identity, Base):
    __tablename__ = "llm_selections"
    __table_args__ = (
        UniqueConstraint("service_id", "scenario"),
        CheckConstraint("scenario IN ('default','analysis','notification')"),
        CheckConstraint("model_enabled IS TRUE"),
        ForeignKeyConstraint(
            ["service_id", "model_config_id", "model_enabled"],
            ["llm_models.service_id", "llm_models.id", "llm_models.enabled"],
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
    )
    service_id: Mapped[str] = mapped_column(ForeignKey("llm_service_config.id"))
    scenario: Mapped[str] = mapped_column(String(30))
    model_config_id: Mapped[str] = mapped_column(
        String(36).with_variant(Uuid(as_uuid=False), "postgresql")
    )
    model_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class LLMCallLog(Identity, Base):
    __tablename__ = "llm_call_logs"
    scenario: Mapped[str] = mapped_column(String(30))
    operation: Mapped[str] = mapped_column(String(30))
    configuration_source: Mapped[str] = mapped_column(String(30))
    revision: Mapped[int | None] = mapped_column(Integer)
    model_id: Mapped[str | None] = mapped_column(String(256))
    outcome_code: Mapped[str] = mapped_column(String(60))
    http_status: Mapped[int | None] = mapped_column(Integer)
    actor_id: Mapped[str] = mapped_column(String(80))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
