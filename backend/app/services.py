import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, inspect, literal, or_, select

from .models import (
    ActualRecord,
    AuditEvent,
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
from .schemas import MilestoneCreate, MilestoneInput, ProjectInput


def fail(status, code, message, fields=None):
    raise HTTPException(
        status, {"code": code, "message": message, "fields": fields or [], "retryable": False}
    )


def record(obj):
    values = {c.key: getattr(obj, c.key) for c in inspect(obj).mapper.column_attrs}
    # SQLite drops tzinfo on read; audit timestamps are always UTC, never business dates.
    for key, value in values.items():
        if isinstance(value, datetime) and value.tzinfo is None:
            values[key] = value.replace(tzinfo=timezone.utc)
    return jsonable_encoder(values)


def get(db, model, key, lock=False):
    try:
        UUID(str(key))
    except ValueError:
        fail(404, "NOT_FOUND", "记录不存在")
    query = select(model).where(model.id == key)
    # Authorization may already have loaded the object before a concurrent writer
    # committed. Refresh the identity map after acquiring the database lock.
    obj = db.scalar(
        query.with_for_update().execution_options(populate_existing=True) if lock else query
    )
    if obj is None:
        fail(404, "NOT_FOUND", "记录不存在")
    return obj


def match(obj, version):
    if version != str(obj.row_version):
        fail(409, "STALE_VERSION", "记录已更新，请刷新后重试")


def plan_item_refs(plan_ids):
    """Nearest node patch wins; exclusions also override inherited rows."""
    lineage = (
        select(
            PlanVersion.id.label("view_plan_id"),
            PlanVersion.id,
            PlanVersion.base_version_id,
            literal(0).label("depth"),
        )
        .where(PlanVersion.id.in_(plan_ids))
        .cte(recursive=True)
    )
    lineage = lineage.union_all(
        select(
            lineage.c.view_plan_id,
            PlanVersion.id,
            PlanVersion.base_version_id,
            (lineage.c.depth + 1).label("depth"),
        ).join(lineage, PlanVersion.id == lineage.c.base_version_id)
    )
    ranked = (
        select(
            lineage.c.view_plan_id,
            PlanItem.id,
            func.row_number()
            .over(
                partition_by=(lineage.c.view_plan_id, PlanItem.milestone_id),
                order_by=lineage.c.depth,
            )
            .label("priority"),
        )
        .join(lineage, PlanItem.plan_version_id == lineage.c.id)
        .subquery()
    )
    return select(ranked.c.view_plan_id, ranked.c.id).where(ranked.c.priority == 1).subquery()


def plan_item_ids(plan_id):
    refs = plan_item_refs([plan_id])
    return select(refs.c.id)


def plan_item(db, plan_id, milestone_id):
    return db.scalar(
        select(PlanItem).where(
            PlanItem.id.in_(plan_item_ids(plan_id)), PlanItem.milestone_id == milestone_id
        )
    )


def current_plan_item(db, project, item):
    return bool(
        project.current_plan_version_id
        and db.scalar(
            select(PlanItem.id).where(
                PlanItem.id == item.id,
                PlanItem.id.in_(plan_item_ids(project.current_plan_version_id)),
                PlanItem.is_included.is_(True),
            )
        )
    )


def materialize_plan_item(db, item, plan_id):
    if item.plan_version_id == plan_id:
        return item
    from .workflow import applicable
    from .workflow_models import ActionItem, ActionLink, ActionTemplate

    copied = PlanItem(
        **{
            column.key: getattr(item, column.key)
            for column in inspect(item).mapper.column_attrs
            if column.key not in ("id", "plan_version_id")
        },
        plan_version_id=plan_id,
    )
    db.add(copied)
    db.flush()
    node = get(db, Milestone, item.milestone_id)
    project = get(db, Project, node.project_id)
    for link in db.scalars(
        select(ActionLink).where(
            ActionLink.plan_item_id == item.id, ActionLink.status.in_(["active", "superseded"])
        )
    ):
        template = get(
            db, ActionTemplate, get(db, ActionItem, link.template_item_id).template_version_id
        )
        db.add(
            ActionLink(
                milestone_id=link.milestone_id,
                plan_item_id=copied.id,
                template_item_id=link.template_item_id,
                assigned_department_id=link.assigned_department_id,
                snapshot_json=link.snapshot_json,
                created_by=db.info.get("actor_id", "system"),
                status="active" if applicable(template, copied, project) else "superseded",
            )
        )
    db.flush()
    return copied


def plan_changes(db, plan):
    if not plan.base_version_id:
        return {}
    from .workflow_models import ActionLink

    patches = list(db.scalars(select(PlanItem).where(PlanItem.plan_version_id == plan.id)))
    if not patches:
        return {}
    previous = {
        item.milestone_id: item
        for item in db.scalars(
            select(PlanItem).where(
                PlanItem.id.in_(plan_item_ids(plan.base_version_id)),
                PlanItem.milestone_id.in_([p.milestone_id for p in patches]),
            )
        )
    }
    actions = {}
    for link in db.scalars(
        select(ActionLink).where(
            ActionLink.plan_item_id.in_([p.id for p in patches] + [p.id for p in previous.values()])
        )
    ):
        actions.setdefault(link.plan_item_id, set()).add(link.template_item_id)
    fields = (
        "milestone_name",
        "node_type_code",
        "planned_date",
        "date_kind",
        "department_id",
        "owner_id",
        "source_ref",
        "is_included",
        "tracking_only",
        "change_reason",
    )
    changes = {}
    for item in patches:
        old = previous.get(item.milestone_id)
        changed_fields = [
            key for key in fields if old is None or getattr(old, key) != getattr(item, key)
        ]
        if old and actions.get(old.id, set()) != actions.get(item.id, set()):
            changed_fields.append("actions")
        if not changed_fields:
            continue
        changes[item.milestone_id] = {
            "kind": "removed"
            if not item.is_included
            else "added"
            if old is None or not old.is_included
            else "changed",
            "old_date": old.planned_date.isoformat() if old else None,
            "new_date": item.planned_date.isoformat(),
            "delta_days": (item.planned_date - old.planned_date).days if old else None,
            "fields": changed_fields,
            "reason": item.change_reason,
        }
    return changes


def audit(db, obj, action, request_id, before=None):
    db.flush()
    db.add(
        AuditEvent(
            aggregate_type=obj.__tablename__,
            aggregate_id=obj.id,
            action=action,
            before_json=before,
            after_json=record(obj),
            request_id=request_id,
            actor_id=db.info.get("actor_id", "system"),
        )
    )


def refs(db, data):
    for key, cls in (("department_id", Department), ("owner_id", User)):
        value = getattr(data, key, None)
        if value:
            try:
                UUID(value)
            except ValueError:
                fail(422, "INVALID_REFERENCE", f"{key} 必须为有效目录ID")
        if value and not db.get(cls, value):
            fail(422, "INVALID_REFERENCE", f"{key} 不在当前目录中")
    if hasattr(data, "node_type_code") and not db.get(NodeType, data.node_type_code):
        fail(422, "INVALID_NODE_TYPE", "请选择已配置的节点类型")


def create_project(db, data: ProjectInput, request_id, source="manual_demo"):
    refs(db, data)
    if db.scalar(select(Project.id).where(Project.project_code == data.project_code)):
        fail(409, "PROJECT_CODE_EXISTS", "项目编号已存在，禁止覆盖")
    project = Project(
        **data.model_dump(), data_source=source, created_by=db.info.get("actor_id", "system")
    )
    db.add(project)
    db.flush()
    editor = db.info.get("actor_id")
    db.add(
        PlanVersion(
            project_id=project.id,
            version_label="V1",
            change_reason="项目初始草稿",
            editor_ids=[editor] if editor else [],
        )
    )
    if editor:
        db.add(ProjectMember(project_id=project.id, user_id=editor, role_code="admin"))
    audit(db, project, "create", request_id)
    return project


def project_detail(db, project):
    result = record(project)
    result["owner_name"] = db.get(User, project.owner_id).display_name if project.owner_id else None
    result["department_name"] = (
        db.get(Department, project.department_id).dept_name if project.department_id else None
    )
    result["milestone_count"] = db.scalar(
        select(func.count()).select_from(Milestone).where(Milestone.project_id == project.id)
    )
    version = (
        db.get(PlanVersion, project.current_plan_version_id)
        if project.current_plan_version_id
        else None
    )
    result["current_plan_label"] = version.version_label if version else None
    return result


def update_project(db, project_id, data, version, request_id):
    project = get(db, Project, project_id, True)
    match(project, version)
    refs(db, data)
    if db.scalar(
        select(Project.id).where(
            Project.project_code == data.project_code, Project.id != project_id
        )
    ):
        fail(409, "PROJECT_CODE_EXISTS", "项目编号已存在")
    before = record(project)
    for key, value in data.model_dump().items():
        setattr(project, key, value)
    if project.project_status in ("completed", "archived"):
        from .workflow import invalidate_plan

        invalidate_plan(db, project.id, "项目关闭", request_id)
    # Even identical saves take a version, to serialize child changes and imports.
    project.row_version += 1
    audit(db, project, "update", request_id, before)
    return project


def create_plan(db, project_id, data, version, request_id):
    project = get(db, Project, project_id, True)
    match(project, version)
    if project.project_status == "archived":
        fail(409, "PROJECT_ARCHIVED", "已归档项目不可新增计划")
    versions = db.scalars(select(PlanVersion).where(PlanVersion.project_id == project_id)).all()
    if any(v.status == "draft" for v in versions):
        fail(409, "DRAFT_EXISTS", "请先使用已有草稿")
    base_id = data.base_version_id or project.current_plan_version_id
    base = get(db, PlanVersion, base_id) if base_id else None
    if base and base.project_id != project_id:
        fail(422, "PLAN_PROJECT_MISMATCH", "计划版本不属于该项目")
    next_number = (
        max(
            (
                int(v.version_label[1:])
                for v in versions
                if v.version_label.startswith("V") and v.version_label[1:].isdigit()
            ),
            default=0,
        )
        + 1
    )
    plan = PlanVersion(
        project_id=project_id,
        version_label=f"V{next_number}",
        base_version_id=base_id,
        change_reason=data.change_reason,
        source_ref=data.source_ref,
        editor_ids=[db.info["actor_id"]] if db.info.get("actor_id") else [],
    )
    db.add(plan)
    db.flush()
    project.row_version += 1
    audit(db, plan, "create_draft", request_id)
    return plan


def draft_plan(db, plan_id, project_id):
    project = get(db, Project, project_id, True)
    if project.project_status == "archived":
        fail(409, "PROJECT_ARCHIVED", "已归档项目不可修改节点计划")
    plan = get(db, PlanVersion, plan_id, True)
    if plan.project_id != project_id:
        fail(422, "PLAN_PROJECT_MISMATCH", "计划版本不属于该项目")
    if plan.status != "draft":
        fail(409, "IMMUTABLE_PLAN", "生效或历史版本不可修改，请先创建变更草稿")
    project.row_version += 1
    plan.row_version += 1
    if db.info.get("actor_id"):
        plan.editor_ids = sorted(set(plan.editor_ids + [db.info["actor_id"]]))
    return plan


def next_milestone_code(db, project_id):
    # create_milestone holds the project lock until the node transaction commits.
    codes = db.scalars(select(Milestone.milestone_code).where(Milestone.project_id == project_id))
    sequence = (
        max(
            (int(m.group(1)) for code in codes if (m := re.search(r"-N([0-9]+)$", code))),
            default=0,
        )
        + 1
    )
    suffix = f"-N{sequence:03d}"
    if len(suffix) >= 64:
        fail(422, "MILESTONE_SEQUENCE_EXHAUSTED", "自动编号超出长度限制，请手动填写节点编号")
    prefix = get(db, Project, project_id).project_code.removeprefix("P-")
    return f"{(prefix or 'NODE')[: 64 - len(suffix)]}{suffix}"


def create_milestone(
    db,
    project_id,
    data: MilestoneInput | MilestoneCreate,
    request_id,
    *,
    matching_source="automatic_node_create",
):
    draft_plan(db, data.plan_version_id, project_id)
    refs(db, data)
    milestone_code = data.milestone_code or next_milestone_code(db, project_id)
    if db.scalar(
        select(Milestone.id).where(
            Milestone.project_id == project_id, Milestone.milestone_code == milestone_code
        )
    ):
        fail(409, "MILESTONE_CODE_EXISTS", "该项目下节点编号已存在，禁止覆盖")
    node = Milestone(
        project_id=project_id,
        milestone_code=milestone_code,
        milestone_name=data.milestone_name,
        node_type_code=data.node_type_code,
    )
    db.add(node)
    db.flush()
    values = data.model_dump(exclude={"milestone_code"})
    db.add(PlanItem(milestone_id=node.id, **values))
    audit(db, node, "create", request_id)
    # Historical seed loading has no principal and must not backfill associations.
    if db.info.get("principal"):
        from .action_matching import automatically_link

        automatically_link(db, node, data.plan_version_id, request_id, matching_source)
    return node


def update_milestone(db, node_id, data, version, request_id):
    node = get(db, Milestone, node_id, True)
    match(node, version)
    draft_plan(db, data.plan_version_id, node.project_id)
    refs(db, data)
    if data.milestone_code != node.milestone_code:
        fail(422, "IMMUTABLE_CODE", "稳定节点编号不可变更")
    item = plan_item(db, data.plan_version_id, node.id)
    if not item:
        fail(404, "PLAN_ITEM_NOT_FOUND", "节点不在该版本中")
    before = record(item)
    values = data.model_dump(exclude={"milestone_code", "plan_version_id"})
    if all(getattr(item, key) == value for key, value in values.items()):
        return node
    item = materialize_plan_item(db, item, data.plan_version_id)
    for key, value in values.items():
        setattr(item, key, value)
    if before["node_type_code"] != item.node_type_code:
        from .workflow import applicable
        from .workflow_models import ActionItem, ActionLink, ActionTemplate

        project = get(db, Project, node.project_id)
        for link in db.scalars(
            select(ActionLink).where(
                ActionLink.plan_item_id == item.id, ActionLink.status == "active"
            )
        ):
            template = get(
                db, ActionTemplate, get(db, ActionItem, link.template_item_id).template_version_id
            )
            if not applicable(template, item, project):
                old = record(link)
                link.status = "superseded"
                audit(db, link, "action_scope_changed", request_id, old)
    node.row_version += 1
    audit(db, item, "edit_draft", request_id, before)
    return node


def activate_plan(db, plan_id, version, approval_ref, request_id):
    plan = get(db, PlanVersion, plan_id)
    project = get(db, Project, plan.project_id, True)
    match(plan, version)
    actor = db.info.get("actor_id")
    if not plan.editor_ids and actor:
        fail(
            409,
            "LEGACY_PLAN_REQUIRES_REVIEW",
            "旧草稿缺少真实编制人，请由编辑人员复核保存后再提交批准",
        )
    if actor and actor in plan.editor_ids:
        fail(403, "SELF_APPROVAL_FORBIDDEN", "计划编制人不能批准自己的计划")
    if project.project_status == "archived" or plan.status != "draft":
        fail(409, "INVALID_STATE_TRANSITION", "仅未归档项目的草稿可批准生效")
    before = record(plan)
    previous_plan_id = project.current_plan_version_id
    if project.current_plan_version_id:
        old = get(db, PlanVersion, project.current_plan_version_id)
        old_before = record(old)
        old.status = "superseded"
        audit(db, old, "supersede", request_id, old_before)
    plan.status = "effective"
    plan.effective_at = now()
    plan.approved_by = actor
    plan.approval_ref = approval_ref
    project.current_plan_version_id = plan.id
    project.row_version += 1
    from zoneinfo import ZoneInfo

    from .config import settings
    from .workflow import invalidate_plan, scan_project
    from .workflow_models import ActionLink, Reminder

    # Restoring an older base needs fresh task references, never revived cancelled history.
    for item in db.scalars(
        select(PlanItem).where(
            PlanItem.id.in_(plan_item_ids(plan.id)),
            PlanItem.plan_version_id != plan.id,
            PlanItem.id.not_in(plan_item_ids(previous_plan_id)),
            or_(
                select(Reminder.id)
                .where(
                    Reminder.milestone_plan_item_id == PlanItem.id, Reminder.status == "invalidated"
                )
                .exists(),
                select(ActionLink.id)
                .where(ActionLink.plan_item_id == PlanItem.id, ActionLink.status == "superseded")
                .exists(),
            ),
        )
    ):
        materialize_plan_item(db, item, plan.id)

    invalidate_plan(db, project.id, "计划版本变更", request_id)
    db.flush()
    scan_project(
        db, project, now().astimezone(ZoneInfo(settings.business_timezone)).date(), request_id, True
    )
    audit(db, plan, "activate", request_id, before)
    audit(db, project, "change_current_plan", request_id)
    return plan


def milestone_detail(db, node, plan_id=None, changes=None):
    result = record(node)
    project = get(db, Project, node.project_id)
    if not plan_id:
        plan_id = project.current_plan_version_id
        if not plan_id:
            plan_id = db.scalar(
                select(PlanVersion.id)
                .where(PlanVersion.project_id == project.id)
                .order_by(PlanVersion.created_at.desc())
            )
    plan = get(db, PlanVersion, plan_id)
    if plan.project_id != node.project_id:
        fail(422, "PLAN_PROJECT_MISMATCH", "版本不属于节点项目")
    item = plan_item(db, plan_id, node.id)
    if not item:
        fail(404, "PLAN_ITEM_NOT_FOUND", "节点不在该版本中")
    result["plan_item"] = {
        **record(item),
        "source_plan_version_id": item.plan_version_id,
        "plan_version_id": plan_id,
    }
    result["plan_change"] = (plan_changes(db, plan) if changes is None else changes).get(node.id)
    result["milestone_name"] = item.milestone_name
    result["node_type_code"] = item.node_type_code
    result["department_name"] = (
        db.get(Department, item.department_id).dept_name if item.department_id else None
    )
    actuals = db.scalars(
        select(ActualRecord)
        .where(ActualRecord.milestone_id == node.id)
        .order_by(ActualRecord.submitted_at.desc(), ActualRecord.id)
    ).all()
    result["actual_records"] = [record(a) for a in actuals]
    result["current_actual"] = next((record(a) for a in actuals if a.is_current), None)
    # Execution fact and verification are separate; phase 1 does not infer performance status.
    result["verification_status"] = actuals[0].verification_status if actuals else "not_submitted"
    return result
