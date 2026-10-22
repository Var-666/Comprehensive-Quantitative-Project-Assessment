from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=500)]
Code = Annotated[str, Field(min_length=1, max_length=64)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ActionItemInput(Input):
    item_code: Annotated[str, Field(min_length=1, max_length=50)]
    title: Annotated[str, Field(min_length=1, max_length=240)]
    materials_required_json: list[Text] = Field(default_factory=list, max_length=30)
    default_department_id: str | None = None
    completion_criteria: Annotated[str, Field(min_length=1, max_length=4000)]


class Applicability(Input):
    project_type: Annotated[str, Field(min_length=1, max_length=60)] | None = None


class TemplateInput(Input):
    template_code: Code
    version_label: Annotated[str, Field(min_length=1, max_length=30)]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    node_type_code: Code
    source_ref: Text
    applicability_json: Applicability = Field(default_factory=Applicability)
    items: list[ActionItemInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_items(self):
        if len({i.item_code for i in self.items}) != len(self.items):
            raise ValueError("动作编号在模板版本内必须唯一")
        return self


class ReviewInput(Input):
    decision: Literal["approved", "returned"]
    approval_ref: Text


class LinkInput(Input):
    plan_item_id: str
    plan_version_id: str | None = None
    template_item_ids: list[str] = Field(min_length=1, max_length=100)


class CalendarDayInput(Input):
    calendar_date: date
    is_workday: bool
    reason: Annotated[str, Field(max_length=160)] = ""


class CalendarInput(Input):
    calendar_code: Code
    version_label: Annotated[str, Field(min_length=1, max_length=30)]
    timezone_name: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    source_ref: Text
    start_date: date
    end_date: date
    days: list[CalendarDayInput] = Field(min_length=1, max_length=3660)

    @model_validator(mode="after")
    def complete(self):
        dates = {d.calendar_date for d in self.days}
        if self.end_date < self.start_date or (self.end_date - self.start_date).days > 3659:
            raise ValueError("日历区间无效或超过3660天")
        if (
            len(dates) != len(self.days)
            or len(dates) != (self.end_date - self.start_date).days + 1
            or min(dates) != self.start_date
            or max(dates) != self.end_date
        ):
            raise ValueError("日历区间内每天必须有且只有一项明确工作日标记")
        return self


class RuleInput(Input):
    rule_code: Code
    version_label: Annotated[str, Field(min_length=1, max_length=30)]
    node_type_code: Code
    source_ref: Text
    days_before: int = Field(ge=0, le=365)
    day_basis: Literal["calendar_day", "workday"]
    calendar_id: str | None = None
    recipient_role_code: Literal["admin", "editor", "reviewer", "viewer"]
    catch_up_days: int = Field(default=0, ge=0, le=365)

    @model_validator(mode="after")
    def calendar(self):
        if self.day_basis == "workday" and not self.calendar_id:
            raise ValueError("工作日规则必须选择日历")
        if self.day_basis == "calendar_day" and self.calendar_id:
            raise ValueError("自然日规则不使用工作日历")
        return self


class DatePreview(Input):
    planned_date: date
    days_before: int = Field(ge=0, le=365)
    day_basis: Literal["calendar_day", "workday"]
    calendar_id: str | None = None


class ScanInput(Input):
    as_of: date
    project_ids: list[str] = Field(min_length=1, max_length=100)


class NotificationEdit(Input):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    body: Annotated[str, Field(min_length=1, max_length=12000)]


class NotificationDecision(Input):
    draft_version: int = Field(ge=1)
    decision: Literal["approved", "returned"]
    comment: Text


class DispatchInput(Input):
    channel: Literal["in_app", "email", "enterprise_messaging"] = "in_app"


class TaskUpdate(Input):
    assignee_id: str | None = None
    status: Literal["todo", "in_progress", "cancelled"] | None = None
    reason: Text


class FeedbackInput(Input):
    comment: Annotated[str, Field(min_length=1, max_length=4000)]
    claimed_completion: bool
    evidence_ref: Text


class VerificationInput(Input):
    decision: Literal["accepted", "returned", "disputed"]
    comment: Text


class MilestoneCompletionInput(Input):
    actual_date: date
    confirmed: Literal[True]


class CancelInput(Input):
    reason: Text
