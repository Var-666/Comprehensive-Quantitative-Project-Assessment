from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProjectInput(Input):
    project_code: str = Field(min_length=1, max_length=64)
    project_name: str = Field(min_length=1, max_length=200)
    project_type: str | None = Field(default=None, max_length=60)
    owner_id: str | None = None
    department_id: str | None = None
    project_status: Literal["draft", "not_started", "active", "completed", "archived"] = (
        "not_started"
    )
    attention_note: str | None = Field(default=None, max_length=2000)
    planned_start: date | None = None
    planned_end: date | None = None

    @model_validator(mode="after")
    def dates(self):
        if self.planned_start and self.planned_end and self.planned_end < self.planned_start:
            raise ValueError("预计结束日期不能早于计划开始日期")
        return self


class PlanCreate(Input):
    base_version_id: str | None = None
    change_reason: str = Field(min_length=1, max_length=2000)
    source_ref: str | None = Field(default=None, max_length=500)


class MilestoneInput(Input):
    plan_version_id: str
    milestone_code: str = Field(min_length=1, max_length=64)
    milestone_name: str = Field(min_length=1, max_length=200)
    node_type_code: str = Field(min_length=1, max_length=64)
    planned_date: date
    date_kind: Literal["contractual", "internal_plan", "unconfirmed"] = "internal_plan"
    department_id: str | None = None
    owner_id: str | None = None
    source_ref: str | None = Field(default=None, max_length=500)
    change_reason: str = Field(min_length=1, max_length=2000)
    tracking_only: bool = False

    @model_validator(mode="after")
    def source(self):
        if self.date_kind == "contractual" and not self.source_ref:
            raise ValueError("合同日期必须保留来源说明；说明不等同于正式附件")
        return self


class MilestoneCreate(MilestoneInput):
    milestone_code: str | None = Field(default=None, min_length=1, max_length=64)
    change_reason: str = Field(default="新增节点", min_length=1, max_length=2000)


class ActualInput(Input):
    actual_date: date | None = None
    completion_flag: bool | None = None
    evidence_ref: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def fact(self):
        if self.completion_flag is True and not self.actual_date:
            raise ValueError("完成记录必须填写实际日期")
        if self.completion_flag is not True and self.actual_date:
            raise ValueError("实际完成日期必须与完成标记一致")
        return self


class VerifyInput(Input):
    decision: Literal["verified", "returned", "disputed"]
    comment: str = Field(min_length=1, max_length=2000)


class ActivateInput(Input):
    approval_ref: str = Field(min_length=1, max_length=500)


class CommitInput(Input):
    preview_hash: str
    include_valid_only: bool = False


class LoginInput(Input):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class MemberInput(Input):
    user_id: str = Field(
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )
    role_code: Literal["admin", "editor", "reviewer", "viewer"]
    active: bool = True
