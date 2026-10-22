"""Deterministic action, reminder and execution services. All mutations share API transactions."""

import hashlib
from datetime import timedelta

from sqlalchemy import select

from . import auth
from .config import settings
from .delivery import deliver
from .models import (
    ActualRecord,
    Credential,
    Department,
    Milestone,
    NodeType,
    PlanItem,
    PlanVersion,
    Project,
    ProjectMember,
    User,
    now,
)
from .services import (
    audit,
    current_plan_item,
    draft_plan,
    fail,
    get,
    materialize_plan_item,
    plan_item,
    plan_item_ids,
    record,
)
from .workflow_models import (
    ActionItem,
    ActionLink,
    ActionTemplate,
    CalendarDay,
    DeliveryAttempt,
    Feedback,
    Notification,
    NotificationReview,
    Reminder,
    ReminderRule,
    Task,
    TaskVerification,
    WorkCalendar,
)


def operator(db):
    if not db.info["principal"].is_system_admin:
        fail(403, "CONFIG_ADMIN_REQUIRED", "只有系统管理员可编制公共模板、规则和日历")


def reviewer(db):
    principal = db.info["principal"]
    if not db.scalar(
        select(ProjectMember.id).where(
            ProjectMember.user_id == principal.user_id,
            ProjectMember.active.is_(True),
            ProjectMember.role_code.in_(["admin", "reviewer"]),
        )
    ):
        fail(403, "REVIEWER_REQUIRED", "需要有效项目审核角色")


def template_detail(db, obj):
    return {
        **record(obj),
        "items": [
            record(i)
            for i in db.scalars(
                select(ActionItem)
                .where(ActionItem.template_version_id == obj.id)
                .order_by(ActionItem.sort_order)
            )
        ],
    }


def write_template(db, data, request_id, obj=None):
    operator(db)
    if not db.get(NodeType, data.node_type_code):
        fail(422, "INVALID_NODE_TYPE", "节点类型不存在")
    if obj and obj.status != "draft":
        fail(409, "IMMUTABLE_CONFIGURATION", "仅草稿可修改；已批准版本需创建新版本")
    before = template_detail(db, obj) if obj else None
    if obj and (data.template_code != obj.template_code or data.version_label != obj.version_label):
        fail(422, "IMMUTABLE_CODE", "编辑草稿不能改变编号和版本")
    values = data.model_dump(exclude={"items"})
    if obj:
        for key, value in values.items():
            setattr(obj, key, value)
        for item in db.scalars(select(ActionItem).where(ActionItem.template_version_id == obj.id)):
            db.delete(item)
        db.flush()
        obj.row_version += 1
        obj.editor_ids = sorted(set(obj.editor_ids + [db.info["actor_id"]]))
    else:
        obj = ActionTemplate(
            **values, created_by=db.info["actor_id"], editor_ids=[db.info["actor_id"]]
        )
        db.add(obj)
        db.flush()
    for n, item in enumerate(data.items):
        if item.default_department_id:
            get(db, Department, item.default_department_id)
        db.add(ActionItem(template_version_id=obj.id, sort_order=n, **item.model_dump()))
    audit(db, obj, "save_template", request_id, before)
    return obj


def submit_config(db, obj, request_id):
    operator(db)
    if obj.status != "draft":
        fail(409, "INVALID_STATE_TRANSITION", "只能提交草稿")
    before = record(obj)
    obj.status = "pending_review"
    # Submission accepts responsibility for the compiled version without changing its creator.
    obj.editor_ids = sorted(set(obj.editor_ids + [db.info["actor_id"]]))
    audit(db, obj, "submit_configuration", request_id, before)


def review_config(db, obj, data, request_id):
    reviewer(db)
    if db.info["actor_id"] in obj.editor_ids:
        fail(403, "SELF_APPROVAL_FORBIDDEN", "编制人员不能批准自己的配置")
    if obj.status != "pending_review":
        fail(409, "INVALID_STATE_TRANSITION", "配置不在待审核状态")
    if isinstance(obj, ReminderRule) and obj.day_basis == "workday" and data.decision == "approved":
        calendar = get(db, WorkCalendar, obj.calendar_id)
        if calendar.status != "approved":
            fail(409, "CALENDAR_NOT_APPROVED", "工作日规则需要已批准的企业日历")
    before = record(obj)
    next_status = "approved" if data.decision == "approved" else "draft"
    obj.approval_ref = data.approval_ref
    obj.approved_by = db.info["actor_id"]
    obj.approved_at = now()
    # New versions supersede the same logical configuration; history stays readable.
    if next_status == "approved":
        code = (
            "template_code"
            if isinstance(obj, ActionTemplate)
            else "rule_code"
            if isinstance(obj, ReminderRule)
            else "calendar_code"
        )
        for old in db.scalars(
            select(type(obj))
            .where(
                getattr(type(obj), code) == getattr(obj, code),
                type(obj).status == "approved",
                type(obj).id != obj.id,
            )
            .with_for_update()
        ):
            retire_config(db, old, "新版配置批准", request_id, permission=False)
    obj.status = next_status
    audit(db, obj, "review_configuration", request_id, before)


def retire_config(db, obj, reason, request_id, permission=True):
    if permission:
        operator(db)
    if obj.status != "approved":
        fail(409, "INVALID_STATE_TRANSITION", "只能停用已批准配置")
    before = record(obj)
    obj.status = "retired"
    if isinstance(obj, ActionTemplate):
        ids = select(ActionItem.id).where(ActionItem.template_version_id == obj.id)
        links = list(
            db.scalars(
                select(ActionLink).where(
                    ActionLink.template_item_id.in_(ids), ActionLink.status == "active"
                )
            )
        )
        affected = {link.plan_item_id for link in links}
        for link in links:
            link.status = "superseded"
            audit(db, link, "template_retired", request_id)
        invalidate(
            db,
            select(Reminder).where(Reminder.milestone_plan_item_id.in_(affected)),
            reason,
            request_id,
        )
    else:
        rule_ids = (
            [obj.id]
            if isinstance(obj, ReminderRule)
            else list(db.scalars(select(ReminderRule.id).where(ReminderRule.calendar_id == obj.id)))
        )
        invalidate(
            db, select(Reminder).where(Reminder.rule_version_id.in_(rule_ids)), reason, request_id
        )
    audit(db, obj, "retire_configuration", request_id, before)


def link_actions(db, node, data, request_id):
    project = get(db, Project, node.project_id, True)
    if project.project_status in ("archived", "completed") or node.lifecycle_status != "active":
        fail(409, "PROJECT_OR_NODE_INACTIVE", "已关闭项目或取消节点不能配置动作")
    item = get(db, PlanItem, data.plan_item_id)
    plan = get(
        db,
        PlanVersion,
        data.plan_version_id
        or (
            project.current_plan_version_id
            if current_plan_item(db, project, item)
            else item.plan_version_id
        ),
    )
    selected = plan_item(db, plan.id, node.id)
    if (
        plan.project_id != node.project_id
        or not selected
        or selected.id != item.id
        or not item.is_included
        or plan.status == "superseded"
    ):
        fail(422, "INVALID_PLAN_ITEM", "请选择节点当前计划或草稿快照")
    existing_ids = set(
        db.scalars(
            select(ActionLink.template_item_id).where(
                ActionLink.plan_item_id == item.id, ActionLink.status == "active"
            )
        )
    )
    if set(data.template_item_ids) - existing_ids:
        if plan.status == "draft":
            draft_plan(db, plan.id, project.id)
        inherited = item.plan_version_id != plan.id
        item = materialize_plan_item(db, item, plan.id)
        if inherited:
            item.change_reason = f"标准动作调整：{plan.change_reason}"[:2000]
    links = []
    for key in dict.fromkeys(data.template_item_ids):
        action = get(db, ActionItem, key)
        template = get(db, ActionTemplate, action.template_version_id)
        if not applicable(template, item, project):
            fail(409, "TEMPLATE_NOT_APPLICABLE", "需要已批准且匹配节点类型/项目类型的模板")
        existing = db.scalar(
            select(ActionLink).where(
                ActionLink.plan_item_id == item.id, ActionLink.template_item_id == action.id
            )
        )
        if existing:
            if existing.status != "active":
                fail(409, "LINK_RETIRED", "历史关联不可重新启用，请选择新模板版本")
            links.append(existing)
            continue
        obj = ActionLink(
            milestone_id=node.id,
            plan_item_id=item.id,
            template_item_id=action.id,
            assigned_department_id=action.default_department_id or item.department_id,
            snapshot_json={
                **record(action),
                "template_code": template.template_code,
                "version_label": template.version_label,
            },
            created_by=db.info["actor_id"],
        )
        db.add(obj)
        audit(db, obj, "link_action", request_id)
        links.append(obj)
    project.row_version += 1
    return links


def applicable(template, item, project):
    return (
        template.status == "approved"
        and template.node_type_code == item.node_type_code
        and (
            not template.applicability_json.get("project_type")
            or template.applicability_json["project_type"] == project.project_type
        )
    )


def trigger_date(db, planned, days, basis, calendar_id):
    if basis == "calendar_day":
        try:
            return planned - timedelta(days=days), None
        except OverflowError:
            return None, "DATE_OUT_OF_RANGE"
    calendar = get(db, WorkCalendar, calendar_id) if calendar_id else None
    if (
        not calendar
        or calendar.status != "approved"
        or calendar.timezone_name != settings.business_timezone
    ):
        return None, "CALENDAR_NOT_APPROVED"
    if not calendar.start_date <= planned <= calendar.end_date:
        return None, "CALENDAR_OUT_OF_RANGE"
    workdays = {
        d.calendar_date: d.is_workday
        for d in db.scalars(select(CalendarDay).where(CalendarDay.calendar_id == calendar.id))
    }
    current = planned
    while days:
        if current <= calendar.start_date:
            return None, "CALENDAR_OUT_OF_RANGE"
        current -= timedelta(days=1)
        if current not in workdays:
            return None, "CALENDAR_INCOMPLETE"
        if workdays[current]:
            days -= 1
    return current, None


def active_recipient(db, user_id, project_id, action="read"):
    return bool(
        db.scalar(
            select(ProjectMember.id)
            .join(Credential, Credential.user_id == ProjectMember.user_id)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
                ProjectMember.active.is_(True),
                ProjectMember.role_code.in_(auth.ROLES[action]),
                Credential.enabled.is_(True),
            )
        )
    )


def scan_project(db, project, as_of, request_id=None, generate=False):
    candidates = []
    if project.project_status in ("archived", "completed") or not project.current_plan_version_id:
        return [
            {
                "project_id": project.id,
                "eligible": False,
                "skipped_reason": "PROJECT_INACTIVE_OR_NO_EFFECTIVE_PLAN",
            }
        ]
    plan = get(db, PlanVersion, project.current_plan_version_id)
    if plan.status != "effective":
        return [
            {"project_id": project.id, "eligible": False, "skipped_reason": "PLAN_NOT_EFFECTIVE"}
        ]
    for item in db.scalars(
        select(PlanItem)
        .where(PlanItem.id.in_(plan_item_ids(plan.id)), PlanItem.is_included.is_(True))
        .order_by(PlanItem.planned_date, PlanItem.id)
    ):
        node = get(db, Milestone, item.milestone_id)
        rules = list(
            db.scalars(
                select(ReminderRule).where(
                    ReminderRule.node_type_code == item.node_type_code,
                    ReminderRule.status == "approved",
                )
            )
        )
        links = list(
            db.scalars(
                select(ActionLink).where(
                    ActionLink.plan_item_id == item.id, ActionLink.status == "active"
                )
            )
        )
        links = [
            link
            for link in links
            if applicable(
                get(
                    db,
                    ActionTemplate,
                    get(db, ActionItem, link.template_item_id).template_version_id,
                ),
                item,
                project,
            )
        ]
        base = {
            "project_id": project.id,
            "milestone_id": node.id,
            "milestone_code": node.milestone_code,
            "milestone_name": item.milestone_name,
            "plan_item_id": item.id,
            "planned_date": item.planned_date.isoformat(),
            "eligible": False,
        }
        reason = None
        if node.lifecycle_status != "active":
            reason = "MILESTONE_CANCELLED"
        elif db.scalar(
            select(ActualRecord.id).where(
                ActualRecord.milestone_id == node.id,
                ActualRecord.is_current.is_(True),
                ActualRecord.verification_status == "verified",
                ActualRecord.completion_flag.is_(True),
            )
        ):
            reason = "VERIFIED_COMPLETED"
        elif not item.source_ref:
            reason = "PLAN_SOURCE_MISSING"
        elif not rules or not links:
            reason = "CONFIGURATION_PENDING"
        if reason:
            candidates.append({**base, "skipped_reason": reason})
            continue
        for rule in rules:
            day, error = trigger_date(
                db, item.planned_date, rule.days_before, rule.day_basis, rule.calendar_id
            )
            row = {
                **base,
                "rule_version_id": rule.id,
                "trigger_date": day.isoformat() if day else None,
            }
            if error:
                candidates.append({**row, "skipped_reason": error})
                continue
            if not 0 <= (as_of - day).days <= rule.catch_up_days:
                candidates.append({**row, "skipped_reason": "OUTSIDE_TRIGGER_WINDOW"})
                continue
            recipients = list(
                db.scalars(
                    select(ProjectMember.user_id)
                    .join(Credential, Credential.user_id == ProjectMember.user_id)
                    .where(
                        ProjectMember.project_id == project.id,
                        ProjectMember.active.is_(True),
                        ProjectMember.role_code == rule.recipient_role_code,
                        Credential.enabled.is_(True),
                    )
                    .distinct()
                )
            )
            if not recipients:
                candidates.append({**row, "skipped_reason": "RECIPIENT_NOT_CONFIGURED"})
            for recipient in recipients:
                key = hashlib.sha256(
                    f"{item.id}:{rule.id}:{day}:{recipient}:1".encode()
                ).hexdigest()
                old = db.scalar(select(Reminder).where(Reminder.idempotency_key == key))
                row2 = {
                    **row,
                    "recipient_user_id": recipient,
                    "eligible": old is None,
                    "skipped_reason": "ALREADY_GENERATED" if old else None,
                    "reminder_id": old.id if old else None,
                }
                if generate and old is None:
                    reminder = Reminder(
                        project_id=project.id,
                        milestone_plan_item_id=item.id,
                        rule_version_id=rule.id,
                        recipient_user_id=recipient,
                        trigger_date=day,
                        idempotency_key=key,
                    )
                    db.add(reminder)
                    db.flush()
                    facts = {
                        "project_code": project.project_code,
                        "project_name": project.project_name,
                        "milestone_id": node.id,
                        "milestone_code": node.milestone_code,
                        "milestone_name": item.milestone_name,
                        "planned_date": item.planned_date.isoformat(),
                        "plan_version": plan.version_label,
                        "plan_item_id": item.id,
                        "source_ref": item.source_ref,
                        "rule_code": rule.rule_code,
                        "rule_version": rule.version_label,
                        "days_before": rule.days_before,
                        "day_basis": rule.day_basis,
                        "trigger_date": day.isoformat(),
                        "recipient_name": get(db, User, recipient).display_name,
                        "actions": [link.snapshot_json for link in links],
                        "generation_mode": "deterministic_template",
                        "sample": settings.demo_mode,
                    }
                    body = (
                        f"根据{facts['plan_version']}计划，{project.project_code} / {item.milestone_name}计划日期为{item.planned_date}。请准备以下事项：\n"
                        + "\n".join(
                            f"{n + 1}. {link.snapshot_json['title']}；核实依据：{link.snapshot_json['completion_criteria']}"
                            for n, link in enumerate(links)
                        )
                        + "\n本通知按已批准规则自动发送，仅用于准备工作；不构成实际完成或收付款确认。"
                    )
                    notification = Notification(
                        project_id=project.id,
                        reminder_instance_id=reminder.id,
                        recipient_user_id=recipient,
                        title=f"{project.project_code} · {item.milestone_name}准备提醒"[:200],
                        body=body,
                        fact_snapshot_json=facts,
                        editor_ids=[],
                    )
                    db.add(notification)
                    for link in links:
                        if not db.scalar(
                            select(Task.id).where(
                                Task.milestone_action_link_id == link.id,
                                Task.rule_version_id == rule.id,
                            )
                        ):
                            task = Task(
                                project_id=project.id,
                                reminder_instance_id=reminder.id,
                                milestone_action_link_id=link.id,
                                rule_version_id=rule.id,
                                due_date=item.planned_date,
                                title=link.snapshot_json["title"],
                                action_snapshot_json=link.snapshot_json,
                            )
                            db.add(task)
                            audit(db, task, "generate_task", request_id)
                    audit(db, reminder, "generate_reminder", request_id)
                    audit(db, notification, "generate_notification", request_id)
                    deliver(db, notification, "in_app", request_id)
                    row2["reminder_id"] = reminder.id
                candidates.append(row2)
    return candidates


def invalidate(db, query, reason, request_id):
    """Keep sent notices and execution history; stop stale drafts and flag started tasks."""
    for reminder in db.scalars(query.where(Reminder.status != "invalidated").with_for_update()):
        before = record(reminder)
        reminder.status = "invalidated"
        reminder.invalidated_reason = reason
        audit(db, reminder, "invalidate", request_id, before)
        for notice in db.scalars(
            select(Notification)
            .where(Notification.reminder_instance_id == reminder.id)
            .with_for_update()
        ):
            if notice.status != "sent":
                before = record(notice)
                notice.status = "invalidated"
                audit(db, notice, "invalidate", request_id, before)
        for task in db.scalars(
            select(Task).where(Task.reminder_instance_id == reminder.id).with_for_update()
        ):
            before = record(task)
            if task.status in ("unassigned", "todo"):
                task.status = "cancelled"
            elif task.status not in ("cancelled", "verified_done"):
                task.requires_review = True
                task.review_reason = reason
            audit(db, task, "source_invalidated", request_id, before)


def invalidate_plan(db, project_id, reason, request_id):
    project = get(db, Project, project_id)
    retained = (
        plan_item_ids(project.current_plan_version_id)
        if (
            project.current_plan_version_id
            and project.project_status not in ("archived", "completed")
        )
        else None
    )
    query = select(Reminder).where(Reminder.project_id == project_id)
    if retained is not None:
        query = query.where(Reminder.milestone_plan_item_id.not_in(retained))
    invalidate(db, query, reason, request_id)
    links = select(ActionLink)
    if retained is not None:
        links = links.where(ActionLink.plan_item_id.not_in(retained))
    for link in db.scalars(
        links.join(PlanItem, ActionLink.plan_item_id == PlanItem.id)
        .join(PlanVersion, PlanItem.plan_version_id == PlanVersion.id)
        .where(
            PlanVersion.project_id == project_id,
            PlanVersion.status == "superseded",
            ActionLink.status == "active",
        )
    ):
        link.status = "superseded"
        audit(db, link, "plan_superseded", request_id)


def live_notice(db, notice):
    reminder = get(db, Reminder, notice.reminder_instance_id)
    item = get(db, PlanItem, reminder.milestone_plan_item_id)
    project = get(db, Project, notice.project_id)
    node = get(db, Milestone, item.milestone_id)
    if (
        reminder.status == "invalidated"
        or not current_plan_item(db, project, item)
        or project.project_status in ("archived", "completed")
        or node.lifecycle_status != "active"
        or not item.is_included
    ):
        fail(409, "SOURCE_INVALIDATED", "计划或节点状态已改变，通知不可继续审核/发送")
    rule = get(db, ReminderRule, reminder.rule_version_id)
    if rule.status != "approved" or (
        rule.day_basis == "workday" and get(db, WorkCalendar, rule.calendar_id).status != "approved"
    ):
        fail(409, "CONFIGURATION_PENDING", "提醒规则或日历已停用")
    if not active_recipient(db, notice.recipient_user_id, notice.project_id):
        fail(409, "RECIPIENT_UNAVAILABLE", "接收人未授权或已禁用")
    for action in notice.fact_snapshot_json["actions"]:
        template = get(db, ActionTemplate, get(db, ActionItem, action["id"]).template_version_id)
        if template.status != "approved":
            fail(409, "CONFIGURATION_PENDING", "通知引用的动作模板已停用，请使用新版重新生成")


def live_task(db, task):
    reminder = get(db, Reminder, task.reminder_instance_id)
    link = get(db, ActionLink, task.milestone_action_link_id)
    item = get(db, PlanItem, link.plan_item_id)
    project = get(db, Project, task.project_id)
    node = get(db, Milestone, item.milestone_id)
    template = get(
        db, ActionTemplate, get(db, ActionItem, link.template_item_id).template_version_id
    )
    if (
        reminder.status == "invalidated"
        or link.status != "active"
        or not current_plan_item(db, project, item)
        or project.project_status in ("archived", "completed")
        or node.lifecycle_status != "active"
        or template.status != "approved"
    ):
        fail(409, "SOURCE_INVALIDATED", "任务来源已改变；保留历史，请取消旧任务并按新版本重新分派")


def notification_detail(db, obj):
    return {
        **record(obj),
        "reviews": [
            record(r)
            for r in db.scalars(
                select(NotificationReview)
                .where(NotificationReview.notification_id == obj.id)
                .order_by(NotificationReview.reviewed_at)
            )
        ],
        "deliveries": [
            record(r)
            for r in db.scalars(
                select(DeliveryAttempt).where(DeliveryAttempt.notification_id == obj.id)
            )
        ],
    }


def task_detail(db, obj):
    feedback = list(
        db.scalars(
            select(Feedback)
            .where(Feedback.task_id == obj.id)
            .order_by(Feedback.submitted_at.desc())
        )
    )
    return {
        **record(obj),
        "feedback": [
            {
                **record(f),
                "verification": record(v)
                if (
                    v := db.scalar(
                        select(TaskVerification).where(TaskVerification.feedback_id == f.id)
                    )
                )
                else None,
            }
            for f in feedback
        ],
    }


def milestone_completion(db, task):
    link = get(db, ActionLink, task.milestone_action_link_id)
    item = get(db, PlanItem, link.plan_item_id)
    node = get(db, Milestone, item.milestone_id)
    project = get(db, Project, task.project_id)
    links = list(
        db.scalars(
            select(ActionLink).where(
                ActionLink.plan_item_id == item.id, ActionLink.status == "active"
            )
        )
    )
    tasks = list(
        db.scalars(
            select(Task)
            .join(ReminderRule, Task.rule_version_id == ReminderRule.id)
            .where(
                Task.milestone_action_link_id.in_([action_link.id for action_link in links]),
                ReminderRule.status == "approved",
            )
        )
    )
    feedback = list(
        db.scalars(
            select(Feedback)
            .join(TaskVerification, TaskVerification.feedback_id == Feedback.id)
            .where(
                Feedback.task_id.in_([t.id for t in tasks]),
                Feedback.status == "verified",
                Feedback.claimed_completion.is_(True),
                TaskVerification.decision == "accepted",
            )
        )
    )
    actuals = list(db.scalars(select(ActualRecord).where(ActualRecord.milestone_id == node.id)))
    current = next(
        (
            a
            for a in actuals
            if a.is_current and a.completion_flag and a.verification_status == "verified"
        ),
        None,
    )
    completed = sum(t.status == "verified_done" and not t.requires_review for t in tasks)
    missing = len(
        {action_link.id for action_link in links} - {t.milestone_action_link_id for t in tasks}
    )
    reason = ""
    if current:
        reason = "节点已核实完成"
    elif (
        not current_plan_item(db, project, item)
        or get(db, PlanVersion, project.current_plan_version_id).status != "effective"
        or project.project_status in ("archived", "completed")
        or node.lifecycle_status != "active"
        or not item.is_included
        or link.status != "active"
        or task.id not in {t.id for t in tasks}
    ):
        reason = "节点或任务来源已变更"
    elif (
        not links or missing or not tasks or completed != len(tasks) or len(feedback) != len(tasks)
    ):
        reason = "标准动作尚未全部核实完成"
    elif any(a.verification_status == "submitted" for a in actuals):
        reason = "已有待核实的节点实际记录，请先处理"
    elif any(get(db, Reminder, t.reminder_instance_id).status == "invalidated" for t in tasks):
        reason = "任务来源已失效，请使用当前配置重新处理"
    elif any(
        not applicable(
            get(
                db,
                ActionTemplate,
                get(db, ActionItem, action_link.template_item_id).template_version_id,
            ),
            item,
            project,
        )
        for action_link in links
    ):
        reason = "标准动作配置已变更"
    principal = db.info["principal"]
    independent = all(f.submitted_by != principal.user_id for f in feedback)
    return {
        "milestone_id": node.id,
        "milestone_name": item.milestone_name,
        "row_version": node.row_version,
        "completed_tasks": completed,
        "total_tasks": len(tasks) + missing,
        "ready": not reason,
        "can_confirm": not reason
        and independent
        and bool(auth.role(db, principal, project.id) & auth.ROLES["review"]),
        "reason": reason,
        "actual_date": current.actual_date.isoformat() if current else None,
        "feedback_ids": [f.id for f in feedback],
    }
