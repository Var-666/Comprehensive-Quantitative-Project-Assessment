"""Read-only, deterministic next steps, scoped to live memberships and source facts."""

from collections import defaultdict
from datetime import date
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from sqlalchemy import select

from . import action_matching, auth
from . import services as svc
from . import workflow as wf
from .config import settings
from .models import (
    ActualRecord,
    Credential,
    Milestone,
    PlanItem,
    PlanVersion,
    Project,
    ProjectMember,
    now,
)
from .workflow_models import CalendarDay, Feedback, Reminder, ReminderRule, Task, WorkCalendar

BUSINESS_TYPES = {
    "create_project": "项目准备",
    "request_access": "访问授权",
    "execute_task": "执行任务",
    "assign_task": "任务分派",
    "verify_feedback": "反馈核实",
    "verify_actual": "节点事实核实",
    "prepare_plan": "计划编制",
    "approve_plan": "计划审批",
    "confirm_matching": "动作候选确认",
    "configure_actions": "标准动作配置",
    "configure_reminders": "提醒配置",
    "confirm_milestone": "节点核销",
    "wait_for_verification": "等待独立核实",
    "supplement_actual": "凭证补充",
    "evaluate": "量化评估",
    "automatic_ready": "自动提醒",
    "review_task_source": "来源复核",
    "idle": "业务状态",
    "check_actual_date": "节点事实核对",
}


def path(project, plan=None, node=None):
    values = {"project": project.id}
    if plan:
        values["plan"] = plan.id
    if node:
        values["node"] = node.id
    return "/milestones?" + urlencode(values)


def next_actions(db, principal):
    today = now().astimezone(ZoneInfo(settings.business_timezone)).date()
    roles = defaultdict(set)
    for member in db.scalars(
        select(ProjectMember).where(
            ProjectMember.user_id == principal.user_id, ProjectMember.active.is_(True)
        )
    ):
        roles[member.project_id].add(member.role_code)
    projects = list(
        db.scalars(
            select(Project).where(Project.id.in_(roles)).order_by(Project.project_code, Project.id)
        )
    )
    recommendations = []
    stages = []

    def add(
        project,
        key,
        action_type,
        title,
        description,
        reason,
        priority,
        target,
        button,
        stage,
        due=None,
        blocked="",
        status=None,
    ):
        recommendations.append(
            {
                "recommendation_id": key,
                "project_id": project.id if project else None,
                "project_code": project.project_code if project else None,
                "project_name": project.project_name if project else None,
                "action_type": action_type,
                "business_type": BUSINESS_TYPES[action_type],
                "title": title,
                "description": description,
                "reason_code": reason,
                "priority": priority,
                "target_path": target,
                "button_label": button,
                "actionable": bool(target),
                "blocked_reason": blocked,
                "stage": stage,
                "status": status or stage,
                "due_date": due.isoformat() if due else None,
            }
        )

    if not projects:
        add(
            None,
            "no-projects",
            "create_project" if principal.is_system_admin else "request_access",
            "创建第一个项目" if principal.is_system_admin else "当前账号尚无项目授权",
            "先创建项目，再录入节点计划与标准动作。"
            if principal.is_system_admin
            else "请联系系统管理员分配项目访问权限。",
            "NO_ACCESSIBLE_PROJECTS",
            30,
            "/projects" if principal.is_system_admin else None,
            "新建项目",
            "项目准备",
            blocked="" if principal.is_system_admin else "当前账号没有项目创建权限",
        )
        return {
            "as_of": today.isoformat(),
            "primary": recommendations[0],
            "secondary": [],
            "projects": [],
        }

    project_by_id = {p.id: p for p in projects}
    plans = list(
        db.scalars(
            select(PlanVersion)
            .where(
                PlanVersion.project_id.in_(project_by_id),
                PlanVersion.status.in_(["draft", "effective"]),
            )
            .order_by(PlanVersion.created_at, PlanVersion.id)
        )
    )
    plans_by_project = defaultdict(list)
    for plan in plans:
        plans_by_project[plan.project_id].append(plan)
    refs = svc.plan_item_refs([p.id for p in plans])
    rows = db.execute(
        select(refs.c.view_plan_id, PlanItem, Milestone)
        .select_from(refs)
        .join(PlanItem, PlanItem.id == refs.c.id)
        .join(Milestone, Milestone.id == PlanItem.milestone_id)
        .order_by(PlanItem.planned_date, Milestone.milestone_code)
    ).all()
    nodes_by_plan, current_items = defaultdict(list), {}
    for plan_id, item, node in rows:
        if item.is_included and node.lifecycle_status == "active":
            nodes_by_plan[plan_id].append((item, node))
            if project_by_id[node.project_id].current_plan_version_id == plan_id:
                current_items[item.id] = (item, node)
    matching_data = action_matching.catalog(db, {item.id for _, item, _ in rows})
    rules = list(
        db.scalars(
            select(ReminderRule)
            .where(ReminderRule.status == "approved")
            .order_by(ReminderRule.rule_code, ReminderRule.id)
        )
    )
    calendars = {
        c.id: c
        for c in db.scalars(
            select(WorkCalendar).where(
                WorkCalendar.id.in_([r.calendar_id for r in rules if r.calendar_id])
            )
        )
    }
    workdays = defaultdict(dict)
    for day in db.scalars(select(CalendarDay).where(CalendarDay.calendar_id.in_(calendars))):
        workdays[day.calendar_id][day.calendar_date] = day.is_workday
    recipient_roles = defaultdict(set)
    for project_id, role in db.execute(
        select(ProjectMember.project_id, ProjectMember.role_code)
        .join(Credential, Credential.user_id == ProjectMember.user_id)
        .where(
            ProjectMember.project_id.in_(project_by_id),
            ProjectMember.active.is_(True),
            Credential.enabled.is_(True),
        )
    ):
        recipient_roles[project_id].add(role)
    actuals = list(
        db.execute(
            select(ActualRecord, Milestone)
            .join(Milestone, Milestone.id == ActualRecord.milestone_id)
            .where(Milestone.project_id.in_(project_by_id))
        )
    )
    verified_nodes = {
        node.id
        for actual, node in actuals
        if actual.is_current
        and actual.verification_status == "verified"
        and actual.completion_flag
        and actual.actual_date
        and actual.actual_date <= today
    }
    approved_rule_ids = {rule.id for rule in rules}

    def source_is_live(task, reminder):
        if (
            task.requires_review
            or reminder.status == "invalidated"
            or task.project_id not in project_by_id
            or task.rule_version_id not in approved_rule_ids
        ):
            return False
        if reminder.milestone_plan_item_id not in current_items:
            return False
        item, _ = current_items[reminder.milestone_plan_item_id]
        project = project_by_id[task.project_id]
        for link in matching_data["links"].get(item.id, []):
            if link.id != task.milestone_action_link_id or link.status != "active":
                continue
            action = matching_data["action_by_id"].get(link.template_item_id)
            return bool(
                action
                and wf.applicable(
                    matching_data["template_by_id"][action.template_version_id], item, project
                )
            )
        return False

    task_rows = list(
        db.execute(
            select(Task, Reminder)
            .join(Reminder, Reminder.id == Task.reminder_instance_id)
            .where(Task.project_id.in_(project_by_id), Task.status != "cancelled")
            .order_by(Task.due_date, Task.id)
        )
    )
    live_tasks = {}
    tasks_by_item = defaultdict(list)
    for task, reminder in task_rows:
        project = project_by_id[task.project_id]
        if project.project_status in ("archived", "completed") or not source_is_live(
            task, reminder
        ):
            if (
                task.requires_review
                and roles[project.id] & auth.ROLES["write"]
                and task.status not in ("cancelled", "verified_done")
            ):
                add(
                    project,
                    task.id + ":source",
                    "review_task_source",
                    "处理来源已变更的旧任务",
                    "取消需复核的旧任务，再按生效计划分派。",
                    "TASK_SOURCE_CHANGED",
                    30,
                    "/tasks?" + urlencode({"tab": "tasks", "task": task.id, "project": project.id}),
                    "检查旧任务",
                    "执行来源复核",
                    task.due_date,
                )
            continue
        live_tasks[task.id] = task
        tasks_by_item[reminder.milestone_plan_item_id].append(task)
        target = "/tasks?" + urlencode({"tab": "tasks", "task": task.id, "project": project.id})
        if (
            task.assignee_id == principal.user_id
            and roles[project.id] & auth.ROLES["write"]
            and task.status in ("todo", "in_progress", "returned")
        ):
            add(
                project,
                task.id + ":execute",
                "execute_task",
                task.title,
                "这是明确分派给当前账号的准备动作，请处理并提交凭证。",
                "MY_TASK_DUE" if task.due_date <= today else "MY_TASK",
                10 if task.due_date <= today else 40,
                target,
                "处理我的任务",
                "执行与独立核实",
                task.due_date,
                status=task.status,
            )
        elif task.assignee_id == principal.user_id and task.status == "submitted":
            add(
                project,
                task.id + ":waiting",
                "wait_for_verification",
                "等待任务反馈独立核实",
                task.title + "已提交，请等待独立核实，无需重复反馈。",
                "MY_FEEDBACK_SUBMITTED",
                70,
                None,
                "",
                "执行与独立核实",
                task.due_date,
                status=task.status,
            )
        elif task.status == "unassigned" and roles[project.id] & auth.ROLES["write"]:
            add(
                project,
                task.id + ":assign",
                "assign_task",
                "分派标准动作执行人",
                task.title + "尚未明确执行人，不会自动指定责任人员。",
                "TASK_UNASSIGNED",
                40,
                target,
                "分派任务",
                "任务分派",
                task.due_date,
            )
    verified_authors = defaultdict(set)
    for feedback in db.scalars(
        select(Feedback)
        .where(Feedback.task_id.in_(live_tasks), Feedback.status.in_(["submitted", "verified"]))
        .order_by(Feedback.submitted_at, Feedback.id)
    ):
        task = live_tasks[feedback.task_id]
        project = project_by_id[task.project_id]
        if feedback.status == "verified" and feedback.claimed_completion:
            verified_authors[task.id].add(feedback.submitted_by)
            continue
        if (
            roles[project.id] & auth.ROLES["review"]
            and feedback.submitted_by != principal.user_id
            and task.status == "submitted"
            and feedback.status == "submitted"
        ):
            add(
                project,
                feedback.id + ":verify",
                "verify_feedback",
                "独立核实任务反馈：" + task.title,
                task.title + "已提交反馈，请核对执行结果与来源凭证。",
                "FEEDBACK_PENDING_REVIEW",
                20,
                "/tasks?" + urlencode({"tab": "tasks", "task": task.id, "project": project.id}),
                "核实任务反馈",
                "执行与独立核实",
                task.due_date,
                status="submitted",
            )
    pending_actual_nodes = {
        node.id for actual, node in actuals if actual.verification_status == "submitted"
    }
    for item_id, tasks in tasks_by_item.items():
        item, node = current_items[item_id]
        if (
            node.id in verified_nodes
            or node.id in pending_actual_nodes
            or not all(t.status == "verified_done" for t in tasks)
        ):
            continue
        links = [
            link for link in matching_data["links"].get(item_id, []) if link.status == "active"
        ]
        if not links or {link.id for link in links} != {
            task.milestone_action_link_id for task in tasks
        }:
            continue
        project = project_by_id[node.project_id]
        can_check = bool(roles[project.id] & auth.ROLES["review"]) and all(
            verified_authors[t.id] and principal.user_id not in verified_authors[t.id]
            for t in tasks
        )
        add(
            project,
            node.id + ":closure",
            "confirm_milestone",
            "检查节点实际完成并核销",
            node.milestone_name
            + "的标准任务已核实；仍需明确确认节点本身是否实际完成，可沿用已有凭证。",
            "MILESTONE_AWAITING_CONFIRMATION",
            25 if can_check else 70,
            "/tasks?" + urlencode({"tab": "tasks", "task": tasks[0].id, "project": project.id})
            if can_check
            else None,
            "查看核销条件",
            "节点确认与核销",
            item.planned_date,
            blocked="" if can_check else "等待未参与任务反馈提交的项目审核人确认实际完成",
        )
    for actual, node in actuals:
        project = project_by_id[node.project_id]
        if project.project_status in ("archived", "completed") or node.lifecycle_status != "active":
            continue
        if (
            actual.is_current
            and actual.verification_status == "verified"
            and actual.completion_flag
            and actual.actual_date
            and actual.actual_date > today
        ):
            can_check = bool(roles[project.id] & (auth.ROLES["write"] | auth.ROLES["review"]))
            add(
                project,
                actual.id + ":date",
                "check_actual_date",
                "核对节点实际日期",
                node.milestone_name
                + "的已核实实际日期晚于当前业务日，请核对来源；评价仍按截止日计算。",
                "ACTUAL_DATE_AFTER_TODAY",
                30,
                path(project, node=node) if can_check else None,
                "查看节点记录",
                "节点事实核对",
                actual.actual_date,
                blocked="" if can_check else "等待项目编辑或核实人员核对日期",
            )
        if (
            actual.verification_status == "submitted"
            and actual.submitted_by != principal.user_id
            and roles[project.id] & auth.ROLES["review"]
        ):
            add(
                project,
                actual.id + ":verify",
                "verify_actual",
                "独立核实节点实际记录：" + node.milestone_name,
                node.milestone_name + "有待核实的完成事实；提交尚不代表已核实。",
                "ACTUAL_PENDING_REVIEW",
                20,
                path(project, node=node),
                "查看节点实际记录",
                "节点事实核实",
                actual.actual_date,
            )
        elif (
            actual.verification_status in ("returned", "disputed")
            and actual.submitted_by == principal.user_id
            and roles[project.id] & auth.ROLES["write"]
        ):
            add(
                project,
                actual.id + ":supplement",
                "supplement_actual",
                "补充节点核实资料",
                node.milestone_name + "的实际记录被退回或存在异议，请补充来源后重新提交。",
                "ACTUAL_NEEDS_EVIDENCE",
                40,
                path(project, node=node),
                "补充核实资料",
                "节点事实核实",
                actual.actual_date,
            )

    for project in projects:
        project_plans = plans_by_project[project.id]
        draft = next((p for p in reversed(project_plans) if p.status == "draft"), None)
        effective = next(
            (
                p
                for p in project_plans
                if p.id == project.current_plan_version_id and p.status == "effective"
            ),
            None,
        )
        plan = draft or effective
        write = bool(roles[project.id] & auth.ROLES["write"])
        review = bool(roles[project.id] & auth.ROLES["review"])
        if project.project_status in ("archived", "completed"):
            stages.append(
                {
                    "project_id": project.id,
                    "project_code": project.project_code,
                    "stage": "项目已关闭",
                }
            )
            continue
        pairs = nodes_by_plan[plan.id] if plan else []
        stage = "节点计划准备" if not pairs else "等待独立审批" if draft else "自动提醒与执行核实"
        if effective and not pairs and not draft:
            add(
                project,
                project.id + ":empty-plan",
                "prepare_plan",
                "补充节点计划",
                "当前生效计划没有可执行节点；请新建变更草稿后录入节点。",
                "EFFECTIVE_PLAN_EMPTY",
                30,
                path(project, effective) if write else None,
                "进入节点管理",
                stage,
                blocked="" if write else "等待项目编辑人员补充节点计划",
            )
        if not effective or draft:
            eligible_review = bool(
                draft
                and pairs
                and review
                and draft.editor_ids
                and principal.user_id not in draft.editor_ids
            )
            add(
                project,
                (plan.id if plan else project.id) + ":plan",
                "approve_plan" if eligible_review else "prepare_plan",
                "独立审批节点计划"
                if eligible_review
                else "完善并检查节点计划"
                if write
                else "等待节点计划独立审批",
                "草稿未生效，不能按该草稿正式触发提醒。已有生效版本继续执行。"
                if effective
                else "当前尚无生效计划，请完善节点及标准动作配置后交由独立人员审批。",
                "PLAN_AWAITING_APPROVAL" if eligible_review else "PLAN_NOT_EFFECTIVE",
                20 if eligible_review else 40,
                path(project, plan) if eligible_review or write else None,
                "进入节点管理",
                stage,
                blocked=""
                if eligible_review or write
                else "当前账号不能批准该计划；等待有权限且未参与编制的人员处理",
                status=plan.status if plan else "尚无节点计划",
            )
        missing = []
        for item, node in pairs:
            if node.id in verified_nodes or item.tracking_only:
                continue
            match = action_matching.describe(
                project, plan, item, node, principal, roles[project.id], matching_data
            )
            if match["status"] not in ("automatic", "manual"):
                missing.append((item, node, match))
        if missing:
            item, node, match = sorted(
                missing,
                key=lambda r: (
                    r[2]["status"] != "conflict",
                    r[0].planned_date,
                    r[1].milestone_code,
                ),
            )[0]
            stage = "标准动作配置待完善"
            can_check = write
            target = (
                path(project, plan, node)
                if can_check
                else "/actions"
                if principal.is_system_admin
                else None
            )
            add(
                project,
                node.id + ":matching",
                "confirm_matching" if match["status"] == "conflict" else "configure_actions",
                "确认多个标准动作候选" if match["status"] == "conflict" else "检查节点标准动作配置",
                f"{len(missing)}个节点需要检查。{node.milestone_code}：{match['label']}。"
                + ("生效计划需新建变更草稿后配置。" if plan.status != "draft" else ""),
                "MATCHING_" + match["status"].upper(),
                30,
                target,
                "检查匹配结果" if can_check else "查看标准动作配置",
                stage,
                item.planned_date,
                blocked=""
                if target
                else "请由项目编辑或配置管理员检查节点类型、项目类型及模板批准状态",
            )
        if effective:
            prerequisite = None
            for item, node in nodes_by_plan[effective.id]:
                if node.id in verified_nodes or item.tracking_only:
                    continue
                applicable_rules = [r for r in rules if r.node_type_code == item.node_type_code]
                if not applicable_rules:
                    prerequisite = "缺少已批准的提醒规则"
                    break
                for rule in applicable_rules:
                    if rule.recipient_role_code not in recipient_roles[project.id]:
                        prerequisite = "提醒规则指定的接收角色没有可用账号或项目授权"
                        break
                    _, error = (
                        wf.trigger_date(
                            db, item.planned_date, rule.days_before, rule.day_basis, None
                        )
                        if rule.day_basis == "calendar_day"
                        else wf.calendar_trigger(
                            calendars.get(rule.calendar_id),
                            workdays[rule.calendar_id],
                            item.planned_date,
                            rule.days_before,
                        )
                    )
                    if error:
                        prerequisite = "提醒工作日历未批准、覆盖不足或日期不可计算"
                        break
                if prerequisite:
                    break
            if prerequisite:
                stage = "提醒配置待完善"
                add(
                    project,
                    project.id + ":rules",
                    "configure_reminders",
                    "完善自动提醒的前置配置",
                    prerequisite + "；未满足条件时系统不会生成无依据通知。",
                    "REMINDER_PREREQUISITE_MISSING",
                    30,
                    "/actions?tab=rules" if principal.is_system_admin else None,
                    "检查提醒规则",
                    stage,
                    blocked=""
                    if principal.is_system_admin
                    else "需配置管理员完善规则、日历或项目接收角色",
                )
            elif not draft and not missing and pairs:
                remaining = [(item, node) for item, node in pairs if node.id not in verified_nodes]
                tracking_only = bool(remaining) and all(item.tracking_only for item, _ in remaining)
                stage = (
                    "节点进展跟踪"
                    if tracking_only
                    else "量化评估与报告"
                    if pairs and all(node.id in verified_nodes for _, node in pairs)
                    else "自动提醒与执行核实"
                )
                add(
                    project,
                    project.id + ":ready",
                    "check_actual_date"
                    if tracking_only
                    else "evaluate"
                    if stage == "量化评估与报告"
                    else "automatic_ready",
                    "记录节点进展与实际完成情况"
                    if tracking_only
                    else "查看量化评估与报告"
                    if stage == "量化评估与报告"
                    else "当前节点已进入自动提醒流程",
                    "当前未完成节点仅跟踪计划和完成情况，无需标准动作，也不生成准备任务和提醒。"
                    if tracking_only
                    else "节点实际完成事实已核实，可查看现有量化口径与报告。"
                    if stage == "量化评估与报告"
                    else "生效计划、标准动作和提醒配置已就绪；到达规则日期后自动站内投递，无需重复操作。",
                    "TRACKING_ONLY_READY"
                    if tracking_only
                    else "VERIFIED_FACTS_AVAILABLE"
                    if stage == "量化评估与报告"
                    else "AUTOMATIC_REMINDERS_READY",
                    80,
                    path(project, effective)
                    if tracking_only
                    else "/metrics"
                    if stage == "量化评估与报告"
                    else None,
                    "查看节点计划" if tracking_only else "查看量化评估",
                    stage,
                )
        stages.append(
            {"project_id": project.id, "project_code": project.project_code, "stage": stage}
        )
    recommendations.sort(
        key=lambda r: (
            r["priority"],
            not r["actionable"],
            r["due_date"] or date.max.isoformat(),
            r["project_code"] or "",
            r["recommendation_id"],
        )
    )
    if not recommendations:
        add(
            None,
            "nothing-pending",
            "idle",
            "当前没有需要处理的事项",
            "可在各业务模块查看已关闭项目及历史记录。",
            "NOTHING_PENDING",
            90,
            None,
            "",
            "暂无待处理事项",
        )
    return {
        "as_of": today.isoformat(),
        "primary": recommendations[0],
        "secondary": recommendations[1:3],
        "projects": stages,
    }
