"""Trial formula trial_v1: deterministic counts, frozen evidence, no composite score."""

import hashlib
import json
from collections import Counter, defaultdict
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select

from .evaluation_models import MetricSnapshot
from .models import ActualRecord, Department, Milestone, PlanItem, PlanVersion, now
from .services import audit, fail, get, record

FORMULA = {
    "version": "trial_v1",
    "status": "confirmed_trial_not_performance_score",
    "on_time_rate": "on_time_completed / (on_time_completed + late_completed) * 100",
    "coverage": "(on_time_completed + late_completed) / due_total * 100",
    "boundary": "按所选计划基准和计算时已核实事实复算业务截止日；不重放历史系统知情状态。未来完成日期不计本次已完成；已核实逾期未完成单列，不进入按期率分母。",
    "score": "未配置综合评价权重，不生成综合得分。",
}
CATEGORIES = [
    "on_time_completed",
    "late_completed",
    "pending_verification",
    "confirmed_overdue_unfinished",
    "not_due",
    "excluded",
]


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def percent(numerator, denominator):
    return (
        str(
            (Decimal(numerator) * 100 / Decimal(denominator)).quantize(
                Decimal(".1"), rounding=ROUND_HALF_UP
            )
        )
        if denominator
        else None
    )


def totals(counts):
    values = {key: counts.get(key, 0) for key in CATEGORIES}
    due = sum(values[k] for k in CATEGORIES[:4])
    verified = values["on_time_completed"] + values["late_completed"]
    return {
        **values,
        "due_total": due,
        "total_nodes": due + values["not_due"],
        "verified_completed": verified,
        "on_time_rate_pct": percent(values["on_time_completed"], verified),
        "completion_verification_coverage_pct": percent(verified, due),
        "composite_score": None,
    }


def calculate(db, project, as_of, plan_id=None):
    plan_id = plan_id or project.current_plan_version_id
    if not plan_id:
        fail(409, "NO_EFFECTIVE_PLAN", "项目尚无生效计划，不能生成评价")
    plan = get(db, PlanVersion, plan_id)
    if plan.project_id != project.id:
        fail(422, "PLAN_PROJECT_MISMATCH", "计划版本不属于本项目")
    if plan.status not in ("effective", "superseded"):
        fail(409, "PLAN_NOT_EFFECTIVE", "草稿计划不能作为评价依据")
    rows = db.execute(
        select(PlanItem, Milestone, ActualRecord, Department.dept_name)
        .join(Milestone, Milestone.id == PlanItem.milestone_id)
        .outerjoin(ActualRecord, ActualRecord.milestone_id == Milestone.id)
        .outerjoin(Department, Department.id == PlanItem.department_id)
        .where(PlanItem.plan_version_id == plan.id)
        .order_by(
            PlanItem.planned_date,
            Milestone.milestone_code,
            ActualRecord.submitted_at,
            ActualRecord.id,
        )
    ).all()
    nodes = {}
    for item, node, actual, department in rows:
        entry = nodes.setdefault(
            node.id, {"item": item, "node": node, "department": department, "actuals": []}
        )
        if actual:
            entry["actuals"].append(actual)
    evidence = []
    for entry in nodes.values():
        item, node, actuals = entry["item"], entry["node"], entry["actuals"]
        current = next(
            (a for a in actuals if a.is_current and a.verification_status == "verified"), None
        )
        category, reason, delta = "pending_verification", "实际事实不足或尚未核实", None
        if not item.is_included or node.lifecycle_status != "active":
            category, reason = "excluded", "节点已取消或不在该计划范围"
        elif item.planned_date > as_of:
            category, reason = "not_due", "统计截止日尚未到期"
        elif (
            current
            and current.completion_flag is True
            and current.actual_date
            and current.actual_date <= as_of
        ):
            delta = (current.actual_date - item.planned_date).days
            category = "on_time_completed" if delta <= 0 else "late_completed"
            reason = (
                "已核实完成且实际日期不晚于计划" if delta <= 0 else "已核实完成且实际日期晚于计划"
            )
        elif current and current.completion_flag is False:
            category, reason = (
                "confirmed_overdue_unfinished",
                "已核实尚未完成；按期率分母处理尚无正式绩效口径",
            )
        elif current and current.actual_date and current.actual_date > as_of:
            reason = "已核实完成日期晚于统计截止日，本次不计已完成"
        evidence.append(
            {
                "milestone_id": node.id,
                "milestone_code": node.milestone_code,
                "milestone_name": item.milestone_name,
                "node_type_code": item.node_type_code,
                "department": entry["department"],
                "plan_item_id": item.id,
                "plan_version_id": plan.id,
                "planned_date": item.planned_date.isoformat(),
                "date_kind": item.date_kind,
                "source_ref": item.source_ref,
                "lifecycle_status": node.lifecycle_status,
                "included": item.is_included,
                "category": category,
                "reason": reason,
                "deviation_days": delta,
                "actual_date": current.actual_date.isoformat()
                if current and current.actual_date
                else None,
                "verified_actual_id": current.id if current else None,
                "actual_records": [record(a) for a in actuals],
            }
        )
    counts = Counter(e["category"] for e in evidence)
    groups = defaultdict(Counter)
    for item in evidence:
        groups[item["node_type_code"]][item["category"]] += 1
    payload = {
        "project_id": project.id,
        "project_code": project.project_code,
        "project_name": project.project_name,
        "as_of_date": as_of.isoformat(),
        "plan_version_id": plan.id,
        "plan_version_label": plan.version_label,
        "plan_status": plan.status,
        "plan_source": plan.source_ref,
        "formula": FORMULA,
        "counts": totals(counts),
        "groups": [
            {"node_type_code": key, **totals(group)} for key, group in sorted(groups.items())
        ],
        "evidence": evidence,
        "knowledge_basis": "current_verified_records_at_calculation",
        "quality": {
            "pending_count": counts["pending_verification"],
            "confirmed_unfinished_count": counts["confirmed_overdue_unfinished"],
            "unconfirmed_plan_dates": sum(
                e["date_kind"] == "unconfirmed" for e in evidence if e["category"] != "excluded"
            ),
            "composite_score_available": False,
        },
        "sample": project.data_source == "sample_excel",
    }
    payload["source_digest"] = digest(payload)
    payload["computed_at"] = now().isoformat()
    return payload


def freeze(db, project, data, request_id):
    payload = calculate(db, project, data.as_of, data.plan_version_id)
    old = db.scalar(
        select(MetricSnapshot).where(
            MetricSnapshot.project_id == project.id,
            MetricSnapshot.source_digest == payload["source_digest"],
        )
    )
    if old:
        return old
    obj = MetricSnapshot(
        project_id=project.id,
        as_of_date=data.as_of,
        plan_version_id=payload["plan_version_id"],
        formula_version=FORMULA["version"],
        source_digest=payload["source_digest"],
        payload_json=payload,
        created_by=db.info["actor_id"],
    )
    db.add(obj)
    audit(db, obj, "freeze_evaluation", request_id)
    return obj
