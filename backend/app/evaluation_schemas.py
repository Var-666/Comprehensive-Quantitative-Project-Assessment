from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .schemas import Input

Text = Annotated[str, Field(min_length=1, max_length=500)]
Amount = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=2, allow_inf_nan=False)]
Code = Annotated[str, Field(min_length=1, max_length=64)]


class SnapshotInput(Input):
    as_of: date
    plan_version_id: str | None = None
    formula_version: Literal["trial_v1"] = "trial_v1"


class FinancialGrant(Input):
    user_id: Annotated[
        str,
        Field(
            pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        ),
    ]
    can_read: bool = False
    can_write: bool = False
    can_verify: bool = False

    @model_validator(mode="after")
    def permissions(self):
        if (self.can_write or self.can_verify) and not self.can_read:
            raise ValueError("写入或核实权限同时需要金额读取权限")
        return self


class FinancialPlanInput(Input):
    record_code: Code
    milestone_id: str | None = None
    direction: Literal["receivable", "payable"]
    planned_date: date
    planned_amount: Amount
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    date_source_kind: Literal["contractual", "internal_plan", "unconfirmed"]
    source_ref: Text


class FinancialActualInput(Input):
    record_code: Code
    financial_plan_id: str | None = None
    direction: Literal["receipt", "payment"]
    actual_date: date
    actual_amount: Amount
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    evidence_ref: Text


class ReviewInput(Input):
    decision: Literal["approved", "returned"]
    comment: Text


class ReportInput(Input):
    metric_snapshot_id: str
    report_type: Literal["stage", "exceptions", "work_plan"] = "stage"
    include_finance: bool = False
    allow_external: bool = False


class AssistInput(Input):
    allow_external: bool = False
