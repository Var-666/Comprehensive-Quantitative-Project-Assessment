"""Money uses Decimal and independent records. Unknown actuals never mean zero or debt."""

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select

from . import auth
from .evaluation_models import FinancialAccess, FinancialActual, FinancialPlan
from .models import Milestone, now
from .services import audit, fail, get, record


def permission(db, principal, project_id, action="read"):
    auth.require_project(
        db, principal, project_id, {"read": "read", "write": "write", "verify": "review"}[action]
    )
    access = db.scalar(
        select(FinancialAccess).where(
            FinancialAccess.project_id == project_id, FinancialAccess.user_id == principal.user_id
        )
    )
    if not access or not getattr(access, "can_" + action):
        fail(403, "FINANCIAL_ACCESS_REQUIRED", "财务金额及核实需要该项目额外授权")
    return access


def allowed(db, principal, project_id):
    return bool(
        db.scalar(
            select(FinancialAccess.id).where(
                FinancialAccess.project_id == project_id,
                FinancialAccess.user_id == principal.user_id,
                FinancialAccess.can_read.is_(True),
            )
        )
    )


def money_record(obj):
    value = record(obj)
    for name in ("planned_amount", "actual_amount"):
        if hasattr(obj, name):
            value[name] = format(getattr(obj, name), ".2f")
    return value


def create_plan(db, project, data, request_id):
    if project.project_status == "archived":
        fail(409, "PROJECT_ARCHIVED", "归档项目不能录入财务记录")
    if data.milestone_id and get(db, Milestone, data.milestone_id).project_id != project.id:
        fail(422, "MILESTONE_PROJECT_MISMATCH", "节点不属于本项目")
    obj = FinancialPlan(project_id=project.id, created_by=db.info["actor_id"], **data.model_dump())
    db.add(obj)
    audit(db, obj, "create_financial_plan", request_id)
    return obj


def create_actual(db, project, data, request_id):
    if project.project_status == "archived":
        fail(409, "PROJECT_ARCHIVED", "归档项目不能录入财务记录")
    if data.financial_plan_id:
        plan = get(db, FinancialPlan, data.financial_plan_id)
        expected = "receipt" if plan.direction == "receivable" else "payment"
        if (
            plan.project_id != project.id
            or plan.currency != data.currency
            or expected != data.direction
        ):
            fail(422, "FINANCIAL_PLAN_MISMATCH", "实际记录的项目、币种或方向与关联计划不一致")
    obj = FinancialActual(
        project_id=project.id, submitted_by=db.info["actor_id"], **data.model_dump()
    )
    db.add(obj)
    audit(db, obj, "submit_financial_actual", request_id)
    return obj


def verify(db, obj, data, request_id):
    if obj.submitted_by == db.info["actor_id"]:
        fail(403, "SELF_VERIFICATION_FORBIDDEN", "财务提交人不能核实自己的记录")
    if obj.verification_status != "submitted":
        fail(409, "ALREADY_REVIEWED", "记录已核实或退回，不能重复处理")
    before = money_record(obj)
    obj.verification_status = data.decision
    obj.verified_by = db.info["actor_id"]
    obj.verified_at = now()
    obj.comment = data.comment
    audit(db, obj, "verify_financial_actual", request_id, before)


def summary(db, project_id, as_of, direction=None, verification=None):
    plans = list(
        db.scalars(
            select(FinancialPlan)
            .where(FinancialPlan.project_id == project_id)
            .order_by(FinancialPlan.planned_date, FinancialPlan.record_code)
        )
    )
    actuals = list(
        db.scalars(
            select(FinancialActual)
            .where(FinancialActual.project_id == project_id, FinancialActual.actual_date <= as_of)
            .order_by(FinancialActual.actual_date, FinancialActual.record_code)
        )
    )
    if direction:
        plans = [p for p in plans if p.direction == direction]
        actuals = [
            a
            for a in actuals
            if a.direction == ("receipt" if direction == "receivable" else "payment")
        ]
    if verification:
        actuals = [a for a in actuals if a.verification_status == verification]
    groups = defaultdict(
        lambda: {
            "planned_total": Decimal(0),
            "planned_due_total": Decimal(0),
            "verified_actual_total": Decimal(0),
            "verified_count": 0,
            "unverified_count": 0,
            "unmatched_plan_count": 0,
        }
    )
    for plan in plans:
        group = groups[(plan.currency, plan.direction)]
        group["planned_total"] += plan.planned_amount
        if plan.planned_date <= as_of:
            group["planned_due_total"] += plan.planned_amount
        if not any(
            a.financial_plan_id == plan.id and a.verification_status == "verified" for a in actuals
        ):
            group["unmatched_plan_count"] += 1
    for actual in actuals:
        group = groups[
            (actual.currency, "receivable" if actual.direction == "receipt" else "payable")
        ]
        if actual.verification_status == "verified":
            group["verified_actual_total"] += actual.actual_amount
            group["verified_count"] += 1
        else:
            group["unverified_count"] += 1
    return {
        "as_of_date": as_of.isoformat(),
        "filters": {"direction": direction, "actual_verification": verification},
        "knowledge_basis": "current_verification_status",
        "actual_data_complete": False,
        "completeness_note": "仅汇总已录入且已核实的记录，无法证明资金台账完整；无实际记录不能认定未发生或欠款。",
        "groups": [
            {
                "currency": key[0],
                "direction": key[1],
                **{k: format(v, ".2f") if isinstance(v, Decimal) else v for k, v in values.items()},
                "verified_actual_total": format(values["verified_actual_total"], ".2f")
                if values["verified_count"]
                else None,
                "actual_data_complete": False,
            }
            for key, values in sorted(groups.items())
        ],
        "plans": [money_record(p) for p in plans],
        "actuals": [money_record(a) for a in actuals],
    }
