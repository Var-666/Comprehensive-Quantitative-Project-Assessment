"""Read-only node readiness, using the same calendar and recipient rules as generation."""

from collections import defaultdict

from sqlalchemy import select

from . import action_matching, auth, services as svc, workflow as wf
from .models import Credential, PlanVersion, Project, ProjectMember
from .workflow_models import CalendarDay, ReminderRule, WorkCalendar

LABELS = {
    "ready": "配置就绪",
    "actions_pending": "待关联标准动作",
    "actions_conflict": "待确认动作模板",
    "actions_approval": "动作模板待批准",
    "reminder_missing": "提醒规则待配置",
    "reminder_approval": "提醒规则待批准",
    "reminder_blocked": "提醒配置需完善",
    "source_missing": "计划依据待补充",
    "tracking_only": "仅时间记录",
    "inactive": "节点已停用",
}
ERRORS = {
    "CALENDAR_NOT_APPROVED": "工作日历未批准或时区不符合业务设置",
    "CALENDAR_OUT_OF_RANGE": "工作日历未覆盖所需日期",
    "CALENDAR_INCOMPLETE": "工作日历缺少所需日期的工作日标记",
    "DATE_OUT_OF_RANGE": "提醒日期超出可计算范围",
}


def catalog(db, project_id):
    rules = list(db.scalars(select(ReminderRule).order_by(ReminderRule.rule_code)))
    calendars = {
        c.id: c
        for c in db.scalars(
            select(WorkCalendar).where(
                WorkCalendar.id.in_([r.calendar_id for r in rules if r.calendar_id])
            )
        )
    }
    days = defaultdict(dict)
    for day in db.scalars(select(CalendarDay).where(CalendarDay.calendar_id.in_(calendars))):
        days[day.calendar_id][day.calendar_date] = day.is_workday
    recipients = defaultdict(set)
    for role, user in db.execute(
        select(ProjectMember.role_code, ProjectMember.user_id)
        .join(Credential, Credential.user_id == ProjectMember.user_id)
        .where(
            ProjectMember.project_id == project_id,
            ProjectMember.active.is_(True),
            Credential.enabled.is_(True),
        )
    ):
        recipients[role].add(user)
    return {
        "rules": rules,
        "calendars": calendars,
        "days": days,
        "recipients": recipients,
        "roles": auth.role(db, db.info["principal"], project_id),
    }


def describe(db, project, plan, item, node, matching, data):
    principal = db.info["principal"]
    roles = data["roles"]
    approved = [
        r
        for r in data["rules"]
        if r.node_type_code == item.node_type_code and r.status == "approved"
    ]
    pending = any(
        r.node_type_code == item.node_type_code and r.status in ("draft", "pending_review")
        for r in data["rules"]
    )
    reminders, issues = [], []
    for rule in approved if not item.tracking_only else []:
        calendar = data["calendars"].get(rule.calendar_id)
        day, error = (
            wf.trigger_date(db, item.planned_date, rule.days_before, rule.day_basis, None)
            if rule.day_basis == "calendar_day"
            else wf.calendar_trigger(
                calendar, data["days"][rule.calendar_id], item.planned_date, rule.days_before
            )
        )
        count = len(data["recipients"][rule.recipient_role_code])
        reason = ERRORS.get(error, "")
        if not count:
            reason = "；".join(filter(None, [reason, "接收角色没有已授权且可用的账号"]))
        reminders.append(
            {
                "id": rule.id,
                "rule_code": rule.rule_code,
                "version_label": rule.version_label,
                "days_before": rule.days_before,
                "day_basis": rule.day_basis,
                "recipient_role_code": rule.recipient_role_code,
                "recipient_count": count,
                "calendar_label": f"{calendar.calendar_code} · {calendar.version_label}"
                if calendar
                else None,
                "trigger_date": day.isoformat() if day else None,
                "reason": reason,
            }
        )
    if item.tracking_only:
        reminder_status, reminder_label = (
            "not_required",
            "仅跟踪计划与完成情况，不生成准备任务和提醒",
        )
    elif not approved:
        reminder_status = "pending_approval" if pending else "missing"
        reminder_label = (
            "尚无已批准提醒规则，请等待独立批准" if pending else "当前节点类型暂无已批准提醒规则"
        )
    elif any(r["reason"] for r in reminders):
        reminder_status, reminder_label = "blocked", "提醒规则已找到，但接收人或日历需完善"
    else:
        reminder_status, reminder_label = "ready", "提醒规则配置已满足"
    action_status = matching["status"]
    state = "ready"
    if item.tracking_only:
        state = "tracking_only"
    elif action_status not in ("automatic", "manual"):
        state = {"conflict": "actions_conflict", "pending_approval": "actions_approval"}.get(
            action_status, "actions_pending"
        )
        issues.append(matching["label"])
    if reminder_status not in ("ready", "not_required"):
        issues.append(reminder_label)
        issues.extend(r["reason"] for r in reminders if r["reason"])
        if state == "ready":
            state = {
                "missing": "reminder_missing",
                "pending_approval": "reminder_approval",
                "blocked": "reminder_blocked",
            }[reminder_status]
    if not item.tracking_only and not item.source_ref:
        issues.append("计划缺少日期依据，无法进入正式提醒流程")
        if state == "ready":
            state = "source_missing"
    if (
        node.lifecycle_status != "active"
        or not item.is_included
        or project.project_status in ("archived", "completed")
    ):
        state = "inactive"
    ready = state in ("ready", "tracking_only")
    next_step = (
        "当前节点已停用，历史记录保留"
        if state == "inactive"
        else "确认使用的动作模板后，再检查提醒配置"
        if state == "actions_conflict"
        else {
            "actions_pending": "请关联已批准动作模板；暂无可用模板时请联系管理员，也可以稍后处理",
            "actions_approval": "请等待动作模板独立批准；也可以继续录入其他节点",
            "reminder_missing": "请联系管理员配置公共提醒规则；可以继续编制其余节点",
            "reminder_approval": "提醒规则需独立批准；可以继续编制其余节点",
            "reminder_blocked": "请查看提醒规则，完善接收角色或工作日历",
            "source_missing": "请返回节点列表，编辑节点并补充日期依据",
        }.get(state, "请完善配置后重新检查，也可以稍后处理")
        if not ready
        else "可以继续录入其他节点，完成本版编制后交由独立审核人员批准整个计划"
        if plan.status == "draft"
        else "配置已就绪；正式提醒仍由现有引擎按触发日和实时权限检查执行"
        if not item.tracking_only
        else "按计划记录进展，并独立核实实际完成情况"
    )
    return {
        "status": state,
        "label": LABELS[state],
        "ready": ready,
        "tracking_only": item.tracking_only,
        "issues": issues,
        "next_step": next_step,
        "actions": matching,
        "reminders": {"status": reminder_status, "label": reminder_label, "rules": reminders},
        "plan": {
            "id": plan.id,
            "version_label": plan.version_label,
            "status": plan.status,
            "can_approve": plan.status == "draft"
            and bool(plan.editor_ids)
            and principal.user_id not in plan.editor_ids
            and bool(roles & auth.ROLES["review"])
            and project.project_status != "archived",
        },
        "can_configure_public": principal.is_system_admin,
    }


def for_node(db, node, plan_id):
    project = svc.get(db, Project, node.project_id)
    plan = svc.get(db, PlanVersion, plan_id)
    matching = action_matching.for_node(db, node, plan.id)
    item = svc.plan_item(db, plan.id, node.id)
    return describe(db, project, plan, item, node, matching, catalog(db, project.id))
