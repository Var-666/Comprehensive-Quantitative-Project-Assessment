from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, inspect, select

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
from .schemas import MilestoneInput, ProjectInput


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
    if base:
        for item in db.scalars(select(PlanItem).where(PlanItem.plan_version_id == base.id)):
            values = record(item)
            for key in ("id", "plan_version_id"):
                values.pop(key)
            values["planned_date"] = item.planned_date
            db.add(PlanItem(**values, plan_version_id=plan.id))
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


def create_milestone(db, project_id, data: MilestoneInput, request_id):
    draft_plan(db, data.plan_version_id, project_id)
    refs(db, data)
    if db.scalar(
        select(Milestone.id).where(
            Milestone.project_id == project_id, Milestone.milestone_code == data.milestone_code
        )
    ):
        fail(409, "MILESTONE_CODE_EXISTS", "该项目下节点编号已存在，禁止覆盖")
    node = Milestone(
        project_id=project_id,
        milestone_code=data.milestone_code,
        milestone_name=data.milestone_name,
        node_type_code=data.node_type_code,
    )
    db.add(node)
    db.flush()
    values = data.model_dump(exclude={"milestone_code"})
    db.add(PlanItem(milestone_id=node.id, **values))
    audit(db, node, "create", request_id)
    return node


def update_milestone(db, node_id, data, version, request_id):
    node = get(db, Milestone, node_id, True)
    match(node, version)
    draft_plan(db, data.plan_version_id, node.project_id)
    refs(db, data)
    if data.milestone_code != node.milestone_code:
        fail(422, "IMMUTABLE_CODE", "稳定节点编号不可变更")
    item = db.scalar(
        select(PlanItem).where(
            PlanItem.milestone_id == node.id, PlanItem.plan_version_id == data.plan_version_id
        )
    )
    if not item:
        fail(404, "PLAN_ITEM_NOT_FOUND", "节点不在该版本中")
    before = record(item)
    for key, value in data.model_dump(exclude={"milestone_code", "plan_version_id"}).items():
        setattr(item, key, value)
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
    audit(db, plan, "activate", request_id, before)
    audit(db, project, "change_current_plan", request_id)
    return plan


def milestone_detail(db, node, plan_id=None):
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
    item = db.scalar(
        select(PlanItem).where(
            PlanItem.milestone_id == node.id, PlanItem.plan_version_id == plan_id
        )
    )
    if not item:
        fail(404, "PLAN_ITEM_NOT_FOUND", "节点不在该版本中")
    result["plan_item"] = record(item)
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
