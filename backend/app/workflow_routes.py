from zoneinfo import ZoneInfo

from fastapi import Header, Query, Request
from sqlalchemy import func, select

from . import auth
from . import services as svc
from . import workflow as wf
from .config import settings
from .models import ActualRecord, AuditEvent, Milestone, NodeType, PlanItem, Project, now
from .workflow_models import (
    ActionLink,
    ActionTemplate,
    CalendarDay,
    Feedback,
    InboxMessage,
    Notification,
    NotificationReview,
    Reminder,
    ReminderRule,
    Task,
    TaskVerification,
    WorkCalendar,
)
from .workflow_schemas import (
    CalendarInput,
    CancelInput,
    DatePreview,
    DispatchInput,
    FeedbackInput,
    LinkInput,
    MilestoneCompletionInput,
    NotificationDecision,
    NotificationEdit,
    ReviewInput,
    RuleInput,
    ScanInput,
    TaskUpdate,
    TemplateInput,
    VerificationInput,
)


def scoped(db, principal, model, key, action="read", lock=False):
    obj = svc.get(db, model, key)
    auth.require_project(db, principal, obj.project_id, action)
    if lock:
        svc.get(db, Project, obj.project_id, True)
        obj = svc.get(db, model, key, True)
    return obj


def page_query(db, query, page, page_size):
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    return total, db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()


def register(app, Db, ok):
    @app.get("/api/v1/milestones/{milestone_id}/configuration-check")
    def configuration_check(request: Request, milestone_id: str, plan_version_id: str, db: Db):
        from .node_configuration import for_node

        return ok(request, for_node(db, svc.get(db, Milestone, milestone_id), plan_version_id))

    @app.get("/api/v1/milestones/{milestone_id}/action-matching")
    def action_matching(request: Request, milestone_id: str, plan_version_id: str, db: Db):
        from .action_matching import for_node

        node = svc.get(db, Milestone, milestone_id)
        return ok(request, for_node(db, node, plan_version_id))

    @app.post("/api/v1/milestones/{milestone_id}/cancel")
    def cancel_node(
        request: Request, milestone_id: str, data: CancelInput, db: Db, if_match: str = Header()
    ):
        node = svc.get(db, Milestone, milestone_id)
        project = svc.get(db, Project, node.project_id, True)
        node = svc.get(db, Milestone, milestone_id, True)
        svc.match(node, if_match)
        if project.project_status == "archived" or node.lifecycle_status != "active":
            svc.fail(409, "INVALID_STATE_TRANSITION", "节点已取消或项目已归档")
        before = svc.record(node)
        node.lifecycle_status = "cancelled"
        node.row_version += 1
        item_ids = select(PlanItem.id).where(PlanItem.milestone_id == node.id)
        wf.invalidate(
            db,
            select(Reminder).where(Reminder.milestone_plan_item_id.in_(item_ids)),
            data.reason,
            request.state.request_id,
        )
        svc.audit(db, node, "cancel_milestone", request.state.request_id, before)
        db.commit()
        return ok(request, svc.record(node))

    @app.get("/api/v1/action-templates")
    def templates(
        request: Request,
        db: Db,
        status: str | None = None,
        node_type: str | None = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ):
        query = select(ActionTemplate)
        if status:
            query = query.where(ActionTemplate.status == status)
        if node_type:
            query = query.where(ActionTemplate.node_type_code == node_type)
        total, objects = page_query(
            db, query.order_by(ActionTemplate.created_at.desc(), ActionTemplate.id), page, page_size
        )
        return ok(
            request,
            {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": [wf.template_detail(db, o) for o in objects],
            },
        )

    @app.get("/api/v1/action-templates/{template_id}")
    def template(request: Request, template_id: str, db: Db):
        return ok(request, wf.template_detail(db, svc.get(db, ActionTemplate, template_id)))

    @app.post("/api/v1/action-templates", status_code=201)
    def create_template(request: Request, data: TemplateInput, db: Db):
        obj = wf.write_template(db, data, request.state.request_id)
        db.commit()
        return ok(request, wf.template_detail(db, obj))

    @app.patch("/api/v1/action-templates/{template_id}")
    def edit_template(
        request: Request, template_id: str, data: TemplateInput, db: Db, if_match: str = Header()
    ):
        obj = svc.get(db, ActionTemplate, template_id, True)
        svc.match(obj, if_match)
        wf.write_template(db, data, request.state.request_id, obj)
        db.commit()
        return ok(request, wf.template_detail(db, obj))

    def register_approval(path, model):
        @app.post(f"/api/v1/{path}/{{config_id}}/submit-review", name=f"submit_{path}")
        def submit(request: Request, config_id: str, db: Db, if_match: str = Header()):
            obj = svc.get(db, model, config_id, True)
            svc.match(obj, if_match)
            wf.submit_config(db, obj, request.state.request_id)
            db.commit()
            return ok(request, svc.record(obj))

        @app.post(f"/api/v1/{path}/{{config_id}}/review", name=f"review_{path}")
        def review(
            request: Request, config_id: str, data: ReviewInput, db: Db, if_match: str = Header()
        ):
            obj = svc.get(db, model, config_id, True)
            svc.match(obj, if_match)
            wf.review_config(db, obj, data, request.state.request_id)
            db.commit()
            return ok(request, svc.record(obj))

        @app.post(f"/api/v1/{path}/{{config_id}}/retire", name=f"retire_{path}")
        def retire(
            request: Request, config_id: str, data: ReviewInput, db: Db, if_match: str = Header()
        ):
            obj = svc.get(db, model, config_id, True)
            svc.match(obj, if_match)
            wf.retire_config(db, obj, data.approval_ref, request.state.request_id)
            db.commit()
            return ok(request, svc.record(obj))

    register_approval("action-templates", ActionTemplate)
    register_approval("reminder-rules", ReminderRule)
    register_approval("work-calendars", WorkCalendar)

    @app.get("/api/v1/work-calendars")
    def calendars(request: Request, db: Db):
        return ok(
            request,
            [
                svc.record(c)
                for c in db.scalars(select(WorkCalendar).order_by(WorkCalendar.created_at.desc()))
            ],
        )

    @app.get("/api/v1/work-calendars/{calendar_id}")
    def calendar(request: Request, calendar_id: str, db: Db):
        obj = svc.get(db, WorkCalendar, calendar_id)
        return ok(
            request,
            {
                **svc.record(obj),
                "days": [
                    svc.record(d)
                    for d in db.scalars(
                        select(CalendarDay)
                        .where(CalendarDay.calendar_id == obj.id)
                        .order_by(CalendarDay.calendar_date)
                    )
                ],
            },
        )

    @app.post("/api/v1/work-calendars", status_code=201)
    def create_calendar(request: Request, data: CalendarInput, db: Db):
        wf.operator(db)
        obj = WorkCalendar(
            **data.model_dump(exclude={"days"}),
            created_by=request.state.principal.user_id,
            editor_ids=[request.state.principal.user_id],
        )
        db.add(obj)
        db.flush()
        for day in data.days:
            db.add(CalendarDay(calendar_id=obj.id, **day.model_dump()))
        svc.audit(db, obj, "create_calendar", request.state.request_id)
        db.commit()
        return ok(request, svc.record(obj))

    @app.get("/api/v1/reminder-rules")
    def rules(request: Request, db: Db):
        return ok(
            request,
            [
                svc.record(r)
                for r in db.scalars(select(ReminderRule).order_by(ReminderRule.created_at.desc()))
            ],
        )

    @app.post("/api/v1/reminder-rules", status_code=201)
    def create_rule(request: Request, data: RuleInput, db: Db):
        wf.operator(db)
        if not db.get(NodeType, data.node_type_code):
            svc.fail(422, "INVALID_NODE_TYPE", "节点类型不存在")
        if data.calendar_id:
            svc.get(db, WorkCalendar, data.calendar_id)
        obj = ReminderRule(
            **data.model_dump(),
            created_by=request.state.principal.user_id,
            editor_ids=[request.state.principal.user_id],
        )
        db.add(obj)
        svc.audit(db, obj, "create_rule", request.state.request_id)
        db.commit()
        return ok(request, svc.record(obj))

    @app.patch("/api/v1/reminder-rules/{rule_id}")
    def edit_rule(
        request: Request, rule_id: str, data: RuleInput, db: Db, if_match: str = Header()
    ):
        wf.operator(db)
        obj = svc.get(db, ReminderRule, rule_id, True)
        svc.match(obj, if_match)
        if obj.status != "draft":
            svc.fail(409, "IMMUTABLE_CONFIGURATION", "仅草稿可编辑，批准后请建立新版本")
        if obj.rule_code != data.rule_code or obj.version_label != data.version_label:
            svc.fail(422, "IMMUTABLE_CODE", "编辑不能改变配置编号和版本")
        if not db.get(NodeType, data.node_type_code):
            svc.fail(422, "INVALID_NODE_TYPE", "节点类型不存在")
        if data.calendar_id:
            svc.get(db, WorkCalendar, data.calendar_id)
        before = svc.record(obj)
        for key, value in data.model_dump().items():
            setattr(obj, key, value)
        obj.row_version += 1
        obj.editor_ids = sorted(set(obj.editor_ids + [request.state.principal.user_id]))
        svc.audit(db, obj, "edit_rule", request.state.request_id, before)
        db.commit()
        return ok(request, svc.record(obj))

    @app.patch("/api/v1/work-calendars/{calendar_id}")
    def edit_calendar(
        request: Request, calendar_id: str, data: CalendarInput, db: Db, if_match: str = Header()
    ):
        wf.operator(db)
        obj = svc.get(db, WorkCalendar, calendar_id, True)
        svc.match(obj, if_match)
        if obj.status != "draft":
            svc.fail(409, "IMMUTABLE_CONFIGURATION", "仅草稿可编辑，批准后请建立新版本")
        if obj.calendar_code != data.calendar_code or obj.version_label != data.version_label:
            svc.fail(422, "IMMUTABLE_CODE", "编辑不能改变配置编号和版本")
        before = svc.record(obj)
        for key, value in data.model_dump(exclude={"days"}).items():
            setattr(obj, key, value)
        for day in db.scalars(select(CalendarDay).where(CalendarDay.calendar_id == obj.id)):
            db.delete(day)
        db.flush()
        for day in data.days:
            db.add(CalendarDay(calendar_id=obj.id, **day.model_dump()))
        obj.row_version += 1
        obj.editor_ids = sorted(set(obj.editor_ids + [request.state.principal.user_id]))
        svc.audit(db, obj, "edit_calendar", request.state.request_id, before)
        db.commit()
        return ok(request, svc.record(obj))

    @app.post("/api/v1/reminder-rules/preview-trigger")
    def preview_trigger(request: Request, data: DatePreview, db: Db):
        day, reason = wf.trigger_date(
            db, data.planned_date, data.days_before, data.day_basis, data.calendar_id
        )
        return ok(
            request,
            {
                "trigger_date": day.isoformat() if day else None,
                "calculable": reason is None,
                "reason": reason,
            },
        )

    @app.get("/api/v1/milestones/{milestone_id}/suggested-actions")
    def suggested(request: Request, milestone_id: str, db: Db, plan_item_id: str):
        node = svc.get(db, Milestone, milestone_id)
        item = svc.get(db, PlanItem, plan_item_id)
        if item.milestone_id != node.id:
            svc.fail(422, "INVALID_PLAN_ITEM", "节点与计划快照不匹配")
        project = svc.get(db, Project, node.project_id)
        return ok(
            request,
            [
                wf.template_detail(db, t)
                for t in db.scalars(
                    select(ActionTemplate).where(ActionTemplate.status == "approved")
                )
                if wf.applicable(t, item, project)
            ],
        )

    @app.get("/api/v1/milestones/{milestone_id}/action-links")
    def links(request: Request, milestone_id: str, db: Db, plan_item_id: str | None = None):
        query = select(ActionLink).where(ActionLink.milestone_id == milestone_id)
        if plan_item_id:
            query = query.where(ActionLink.plan_item_id == plan_item_id)
        return ok(
            request, [svc.record(o) for o in db.scalars(query.order_by(ActionLink.created_at))]
        )

    @app.post("/api/v1/milestones/{milestone_id}/action-links")
    def bind(request: Request, milestone_id: str, data: LinkInput, db: Db):
        node = svc.get(db, Milestone, milestone_id)
        objects = wf.link_actions(db, node, data, request.state.request_id)
        db.commit()
        return ok(request, [svc.record(o) for o in objects])

    @app.post("/api/v1/reminder-jobs/simulate")
    @app.post("/api/v1/reminder-jobs/run")
    def scan(request: Request, data: ScanInput, db: Db):
        generate = request.url.path.endswith("/run")
        if generate:
            wf.operator(db)
            if (
                settings.app_env == "production"
                and data.as_of != now().astimezone(ZoneInfo(settings.business_timezone)).date()
            ):
                svc.fail(422, "SCAN_DATE_RESTRICTED", "正式扫描只接受当前业务日期")
        rows = []
        for project_id in sorted(set(data.project_ids)):
            auth.require_project(db, request.state.principal, project_id)
            project = svc.get(db, Project, project_id, generate)
            rows.extend(
                wf.scan_project(db, project, data.as_of, request.state.request_id, generate)
            )
        db.commit()
        return ok(
            request,
            {
                "as_of": data.as_of.isoformat(),
                "generated": sum(r["eligible"] for r in rows) if generate else 0,
                "items": rows,
            },
        )

    @app.get("/api/v1/reminders")
    def reminders(
        request: Request,
        db: Db,
        project_id: str | None = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ):
        query = select(Reminder).where(
            Reminder.project_id.in_(auth.visible_projects(request.state.principal))
        )
        if project_id:
            auth.require_project(db, request.state.principal, project_id)
            query = query.where(Reminder.project_id == project_id)
        total, values = page_query(
            db, query.order_by(Reminder.generated_at.desc(), Reminder.id), page, page_size
        )
        return ok(
            request,
            {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": [svc.record(o) for o in values],
            },
        )

    @app.get("/api/v1/notifications")
    def notifications(
        request: Request,
        db: Db,
        project_id: str | None = None,
        status: str | None = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ):
        query = select(Notification).where(
            Notification.project_id.in_(auth.visible_projects(request.state.principal))
        )
        if project_id:
            auth.require_project(db, request.state.principal, project_id)
            query = query.where(Notification.project_id == project_id)
        if status:
            query = query.where(Notification.status == status)
        total, values = page_query(
            db, query.order_by(Notification.created_at.desc(), Notification.id), page, page_size
        )
        return ok(
            request,
            {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": [wf.notification_detail(db, o) for o in values],
            },
        )

    @app.get("/api/v1/notifications/{notification_id}")
    def notice(request: Request, notification_id: str, db: Db):
        return ok(
            request,
            wf.notification_detail(
                db, scoped(db, request.state.principal, Notification, notification_id)
            ),
        )

    @app.patch("/api/v1/notifications/{notification_id}/draft")
    def edit_notice(
        request: Request,
        notification_id: str,
        data: NotificationEdit,
        db: Db,
        if_match: str = Header(),
    ):
        obj = scoped(db, request.state.principal, Notification, notification_id, "write", True)
        svc.match(obj, if_match)
        wf.live_notice(db, obj)
        if obj.status not in ("draft", "returned"):
            svc.fail(409, "IMMUTABLE_DRAFT", "仅草稿或退回稿可修改")
        before = svc.record(obj)
        obj.title, obj.body = data.title, data.body
        obj.draft_version += 1
        obj.editor_ids = sorted(set(obj.editor_ids + [request.state.principal.user_id]))
        obj.status = "draft"
        svc.audit(db, obj, "edit_draft", request.state.request_id, before)
        db.commit()
        return ok(request, wf.notification_detail(db, obj))

    @app.post("/api/v1/notifications/{notification_id}/submit-review")
    def submit_notice(request: Request, notification_id: str, db: Db, if_match: str = Header()):
        obj = scoped(db, request.state.principal, Notification, notification_id, "write", True)
        svc.match(obj, if_match)
        wf.live_notice(db, obj)
        if obj.status not in ("draft", "returned"):
            svc.fail(409, "INVALID_STATE_TRANSITION", "只有草稿可提交审核")
        before = svc.record(obj)
        obj.status = "pending_review"
        obj.submitted_by = request.state.principal.user_id
        obj.editor_ids = sorted(set(obj.editor_ids + [request.state.principal.user_id]))
        svc.audit(db, obj, "submit_review", request.state.request_id, before)
        db.commit()
        return ok(request, wf.notification_detail(db, obj))

    @app.post("/api/v1/notifications/{notification_id}/review")
    def review_notice(
        request: Request,
        notification_id: str,
        data: NotificationDecision,
        db: Db,
        if_match: str = Header(),
    ):
        obj = scoped(db, request.state.principal, Notification, notification_id, "review", True)
        svc.match(obj, if_match)
        wf.live_notice(db, obj)
        if request.state.principal.user_id in obj.editor_ids:
            svc.fail(403, "SELF_APPROVAL_FORBIDDEN", "通知编制或提交人不能审核自己的草稿")
        if obj.status != "pending_review" or data.draft_version != obj.draft_version:
            svc.fail(409, "DRAFT_VERSION_CONFLICT", "通知不在待审状态或内容版本已变化")
        before = svc.record(obj)
        obj.status = "approved_pending_send" if data.decision == "approved" else "returned"
        db.add(
            NotificationReview(
                notification_id=obj.id,
                draft_version=obj.draft_version,
                decision=data.decision,
                comment=data.comment,
                reviewer_id=request.state.principal.user_id,
            )
        )
        svc.audit(db, obj, "review_notice", request.state.request_id, before)
        db.commit()
        return ok(request, wf.notification_detail(db, obj))

    @app.post("/api/v1/notifications/{notification_id}/dispatch")
    def dispatch(
        request: Request,
        notification_id: str,
        data: DispatchInput,
        db: Db,
        if_match: str = Header(),
    ):
        obj = scoped(db, request.state.principal, Notification, notification_id, "write", True)
        # The unique inbox record and locked notification make retries safe, even after status changed.
        if obj.status == "sent" and data.channel == "in_app":
            return ok(request, wf.notification_detail(db, obj))
        svc.match(obj, if_match)
        wf.live_notice(db, obj)
        if obj.status != "approved_pending_send":
            svc.fail(409, "NOT_APPROVED", "通知必须先通过独立审核")
        from .delivery import deliver

        deliver(db, obj, data.channel, request.state.request_id)
        db.commit()
        return ok(request, wf.notification_detail(db, obj))

    @app.get("/api/v1/inbox")
    def inbox(request: Request, db: Db):
        query = (
            select(InboxMessage)
            .join(Notification, Notification.id == InboxMessage.notification_id)
            .where(
                InboxMessage.recipient_user_id == request.state.principal.user_id,
                Notification.project_id.in_(auth.visible_projects(request.state.principal)),
            )
            .order_by(InboxMessage.created_at.desc())
        )
        return ok(request, [svc.record(m) for m in db.scalars(query)])

    @app.post("/api/v1/inbox/{message_id}/read")
    def read_message(request: Request, message_id: str, db: Db):
        obj = svc.get(db, InboxMessage, message_id, True)
        if obj.recipient_user_id != request.state.principal.user_id:
            svc.fail(404, "NOT_FOUND", "消息不存在")
        scoped(db, request.state.principal, Notification, obj.notification_id)
        obj.read_at = obj.read_at or now()
        db.commit()
        return ok(request, svc.record(obj))

    @app.get("/api/v1/tasks")
    def tasks(
        request: Request,
        db: Db,
        project_id: str | None = None,
        status: str | None = None,
        mine: bool = False,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ):
        query = select(Task).where(
            Task.project_id.in_(auth.visible_projects(request.state.principal))
        )
        if project_id:
            auth.require_project(db, request.state.principal, project_id)
            query = query.where(Task.project_id == project_id)
        if status:
            query = query.where(Task.status == status)
        if mine:
            query = query.where(Task.assignee_id == request.state.principal.user_id)
        total, values = page_query(
            db, query.order_by(Task.created_at.desc(), Task.id), page, page_size
        )
        return ok(
            request,
            {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": [wf.task_detail(db, o) for o in values],
            },
        )

    @app.get("/api/v1/tasks/{task_id}")
    def task(request: Request, task_id: str, db: Db):
        obj = scoped(db, request.state.principal, Task, task_id)
        return ok(
            request,
            {
                **wf.task_detail(db, obj),
                "milestone_completion": wf.milestone_completion(db, obj),
            },
        )

    @app.post("/api/v1/tasks/{task_id}/complete-milestone")
    def complete_milestone(
        request: Request,
        task_id: str,
        data: MilestoneCompletionInput,
        db: Db,
        if_match: str = Header(),
    ):
        obj = scoped(db, request.state.principal, Task, task_id, "review", True)
        state = wf.milestone_completion(db, obj)
        node = svc.get(db, Milestone, state["milestone_id"], True)
        if state["actual_date"]:
            if state["actual_date"] != data.actual_date.isoformat():
                svc.fail(409, "ALREADY_COMPLETED", "节点已核销，不能在此修改实际日期")
            return ok(request, wf.task_detail(db, obj))
        svc.match(node, if_match)
        if not state["ready"]:
            svc.fail(409, "MILESTONE_NOT_READY", state["reason"])
        if not state["can_confirm"]:
            svc.fail(403, "SELF_VERIFICATION_FORBIDDEN", "任务反馈提交人不能核销自己的节点完成事实")
        wf.live_task(db, obj)
        feedback = list(db.scalars(select(Feedback).where(Feedback.id.in_(state["feedback_ids"]))))
        for old in db.scalars(
            select(ActualRecord).where(
                ActualRecord.milestone_id == node.id, ActualRecord.is_current.is_(True)
            )
        ):
            before = svc.record(old)
            old.is_current = False
            svc.audit(db, old, "supersede_fact", request.state.request_id, before)
        db.flush()
        actual = ActualRecord(
            milestone_id=node.id,
            actual_date=data.actual_date,
            completion_flag=True,
            verification_status="verified",
            is_current=True,
            submitted_by="task-workflow",
            verified_by=request.state.principal.user_id,
            verified_at=now(),
            evidence_ref=f"沿用已核实的{len(feedback)}项标准任务凭证；详见任务反馈及核销记录",
            comment="审核人已明确确认节点实际完成。沿用任务反馈：\n"
            + "\n".join(f"{f.id}：{f.evidence_ref}" for f in feedback),
        )
        db.add(actual)
        node.row_version += 1
        svc.audit(db, actual, "complete_milestone_from_tasks", request.state.request_id)
        item_ids = select(PlanItem.id).where(PlanItem.milestone_id == node.id)
        wf.invalidate(
            db,
            select(Reminder).where(Reminder.milestone_plan_item_id.in_(item_ids)),
            "节点已核实完成",
            request.state.request_id,
        )
        db.commit()
        return ok(request, wf.task_detail(db, obj))

    @app.patch("/api/v1/tasks/{task_id}")
    def update_task(
        request: Request, task_id: str, data: TaskUpdate, db: Db, if_match: str = Header()
    ):
        obj = scoped(db, request.state.principal, Task, task_id, "write", True)
        svc.match(obj, if_match)
        principal = request.state.principal
        assigning = "assignee_id" in data.model_fields_set or data.status == "cancelled"
        if assigning:
            auth.require_project(db, principal, obj.project_id, "write")
        elif obj.assignee_id != principal.user_id:
            svc.fail(403, "ASSIGNEE_REQUIRED", "只有任务执行人可以更新执行状态")
        if obj.requires_review and data.status != "cancelled":
            svc.fail(409, "SOURCE_REQUIRES_REVIEW", "来源变化，需编辑取消旧任务并按新版重新分派")
        if data.status != "cancelled":
            wf.live_task(db, obj)
        if obj.status in ("verified_done", "cancelled") or (
            obj.status == "submitted" and not (obj.requires_review and data.status == "cancelled")
        ):
            svc.fail(409, "INVALID_STATE_TRANSITION", "已提交核实/完成/取消的任务不可修改")
        before = svc.record(obj)
        if "assignee_id" in data.model_fields_set:
            if not data.assignee_id or not wf.active_recipient(
                db, data.assignee_id, obj.project_id, "write"
            ):
                svc.fail(
                    422,
                    "INVALID_ASSIGNEE",
                    "执行人必须具有当前项目编辑权限和可用账号，不能是只读角色",
                )
            obj.assignee_id = data.assignee_id
            obj.status = "todo"
        if data.status:
            if data.status != "cancelled" and not obj.assignee_id:
                svc.fail(409, "ASSIGNEE_REQUIRED", "请先分派负责人")
            obj.status = data.status
        svc.audit(db, obj, "update_task", request.state.request_id, before)
        db.commit()
        return ok(request, wf.task_detail(db, obj))

    @app.post("/api/v1/tasks/{task_id}/feedback", status_code=201)
    def feedback(
        request: Request, task_id: str, data: FeedbackInput, db: Db, if_match: str = Header()
    ):
        obj = scoped(db, request.state.principal, Task, task_id, "write", True)
        svc.match(obj, if_match)
        if obj.assignee_id != request.state.principal.user_id:
            svc.fail(403, "ASSIGNEE_REQUIRED", "只有任务执行人可提交反馈")
        wf.live_task(db, obj)
        if obj.requires_review or obj.status not in ("todo", "in_progress", "returned"):
            svc.fail(409, "INVALID_STATE_TRANSITION", "任务不可提交反馈或来源需复核")
        before = svc.record(obj)
        result = Feedback(
            task_id=obj.id, submitted_by=request.state.principal.user_id, **data.model_dump()
        )
        db.add(result)
        obj.status = "submitted"
        svc.audit(db, result, "submit_feedback", request.state.request_id)
        svc.audit(db, obj, "submit_feedback", request.state.request_id, before)
        db.commit()
        return ok(request, svc.record(result))

    @app.post("/api/v1/task-feedback/{feedback_id}/verify")
    def verify(request: Request, feedback_id: str, data: VerificationInput, db: Db):
        feedback = svc.get(db, Feedback, feedback_id)
        obj = scoped(db, request.state.principal, Task, feedback.task_id, "review", True)
        db.refresh(feedback)
        if feedback.submitted_by == request.state.principal.user_id:
            svc.fail(403, "SELF_VERIFICATION_FORBIDDEN", "反馈提交人不能核实自己的反馈")
        wf.live_task(db, obj)
        if obj.requires_review or feedback.status != "submitted" or obj.status != "submitted":
            svc.fail(409, "INVALID_STATE_TRANSITION", "反馈已核实或来源需复核")
        before = svc.record(obj)
        feedback.status = "verified" if data.decision == "accepted" else data.decision
        obj.status = (
            "verified_done"
            if data.decision == "accepted" and feedback.claimed_completion
            else "in_progress"
            if data.decision == "accepted"
            else "returned"
        )
        db.add(
            TaskVerification(
                feedback_id=feedback.id,
                decision=data.decision,
                comment=data.comment,
                reviewer_id=request.state.principal.user_id,
            )
        )
        svc.audit(db, feedback, "verify_feedback", request.state.request_id)
        svc.audit(db, obj, "verify_feedback", request.state.request_id, before)
        db.commit()
        return ok(request, wf.task_detail(db, obj))

    @app.get("/api/v1/tasks/{task_id}/audit-events")
    def task_audit(request: Request, task_id: str, db: Db):
        scoped(db, request.state.principal, Task, task_id)
        ids = list(db.scalars(select(Feedback.id).where(Feedback.task_id == task_id)))
        return ok(
            request,
            [
                svc.record(e)
                for e in db.scalars(
                    select(AuditEvent)
                    .where(AuditEvent.aggregate_id.in_([task_id, *ids]))
                    .order_by(AuditEvent.occurred_at.desc())
                )
            ],
        )
