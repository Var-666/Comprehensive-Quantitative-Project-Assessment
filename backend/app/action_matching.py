"""Deterministic template matching; reads never backfill historical associations."""

from collections import defaultdict

from sqlalchemy import select

from . import auth
from . import services as svc
from . import workflow as wf
from .models import Department, PlanVersion, Project
from .workflow_models import ActionItem, ActionLink, ActionTemplate
from .workflow_schemas import LinkInput

LABELS = {
    "tracking_only": "仅时间记录，无需标准动作",
    "automatic": "系统已自动匹配",
    "manual": "已人工关联",
    "conflict": "存在多个候选待确认",
    "missing": "没有匹配的已批准标准动作",
    "pending_approval": "模板待业务确认",
    "needs_review": "原动作关联需复核",
}


def catalog(db, item_ids):
    templates = list(
        db.scalars(
            select(ActionTemplate).order_by(
                ActionTemplate.template_code, ActionTemplate.version_label, ActionTemplate.id
            )
        )
    )
    items, links = defaultdict(list), defaultdict(list)
    for item in db.scalars(select(ActionItem).order_by(ActionItem.sort_order, ActionItem.id)):
        items[item.template_version_id].append(item)
    for link in db.scalars(
        select(ActionLink).where(ActionLink.plan_item_id.in_(item_ids)).order_by(ActionLink.id)
    ):
        links[link.plan_item_id].append(link)
    departments = {d.id: d.dept_name for d in db.scalars(select(Department))}
    return {
        "templates": templates,
        "items": items,
        "links": links,
        "departments": departments,
        "template_by_id": {t.id: t for t in templates},
        "action_by_id": {a.id: a for group in items.values() for a in group},
    }


def describe(project, plan, item, node, principal, roles, data):
    candidates = [t for t in data["templates"] if wf.applicable(t, item, project)]
    all_links = data["links"].get(item.id, [])
    templates = data["template_by_id"]
    actions = data["action_by_id"]
    valid = [
        link
        for link in all_links
        if not item.tracking_only
        and link.status == "active"
        and link.template_item_id in actions
        and wf.applicable(
            templates[actions[link.template_item_id].template_version_id], item, project
        )
    ]
    if item.tracking_only:
        status = "tracking_only"
    elif valid:
        status = (
            "automatic"
            if all(
                link.snapshot_json.get("link_source", "manual").startswith("automatic_")
                for link in valid
            )
            else "manual"
        )
    elif all_links:
        status = "needs_review"
    elif len(candidates) > 1:
        status = "conflict"
    elif len(candidates) == 1:
        status = "missing"
    elif any(
        t.status in ("draft", "pending_review") and wf.scope_applies(t, item, project)
        for t in data["templates"]
    ):
        status = "pending_approval"
    else:
        status = "missing"
    writable = (
        bool(roles & auth.ROLES["write"])
        and plan.status == "draft"
        and node.lifecycle_status == "active"
        and item.is_included
        and project.project_status not in ("archived", "completed")
    )
    label = LABELS[status]
    if not item.tracking_only and not all_links and len(candidates) == 1:
        label = "找到唯一适用模板，待人工确认关联"
    blocked = "" if writable else "当前节点不允许修改；请由项目编辑人员在草稿计划中配置"
    return {
        "status": status,
        "label": label,
        "can_modify": writable,
        "blocked_reason": blocked,
        "action_count": len(valid),
        "candidate_count": len(candidates),
        "candidates": [
            {
                "id": t.id,
                "title": t.title,
                "template_code": t.template_code,
                "version_label": t.version_label,
                "node_type_code": t.node_type_code,
                "applicability_json": t.applicability_json,
                "items": [
                    {
                        **svc.record(a),
                        "department_name": data["departments"].get(
                            a.default_department_id or item.department_id
                        ),
                    }
                    for a in data["items"][t.id]
                ],
            }
            for t in candidates
        ],
        "links": [
            {
                **svc.record(link),
                "department_name": data["departments"].get(link.assigned_department_id),
                "source": link.snapshot_json.get("link_source", "manual"),
                "template_title": link.snapshot_json.get("template_title", "历史模板快照"),
                "applicable": link in valid,
            }
            for link in all_links
        ],
    }


def for_node(db, node, plan_id):
    project = svc.get(db, Project, node.project_id)
    plan = svc.get(db, PlanVersion, plan_id)
    if plan.project_id != project.id:
        svc.fail(422, "PLAN_PROJECT_MISMATCH", "版本不属于节点项目")
    item = svc.plan_item(db, plan.id, node.id)
    if not item:
        svc.fail(404, "PLAN_ITEM_NOT_FOUND", "节点不在该版本中")
    principal = db.info["principal"]
    return describe(
        project,
        plan,
        item,
        node,
        principal,
        auth.role(db, principal, project.id),
        catalog(db, [item.id]),
    )


def automatically_link(db, node, plan_id, request_id, source):
    principal = db.info["principal"]
    auth.require_project(db, principal, node.project_id, "write")
    project = svc.get(db, Project, node.project_id, True)
    if project.project_status in ("archived", "completed") or node.lifecycle_status != "active":
        return
    plan = svc.get(db, PlanVersion, plan_id, True)
    item = svc.plan_item(db, plan.id, node.id)
    if (
        plan.project_id != project.id
        or plan.status != "draft"
        or not item
        or item.plan_version_id != plan.id
    ):
        svc.fail(409, "IMMUTABLE_PLAN", "自动关联仅用于本次写入的草稿节点")
    if db.scalar(select(ActionLink.id).where(ActionLink.plan_item_id == item.id)):
        return
    if item.tracking_only:
        return
    candidates = [
        t
        for t in db.scalars(select(ActionTemplate).where(ActionTemplate.status == "approved"))
        if wf.applicable(t, item, project)
    ]
    if len(candidates) != 1:
        return
    # Lock and refresh the chosen approved version so retirement cannot race the snapshot write.
    template = svc.get(db, ActionTemplate, candidates[0].id, True)
    candidates = [
        t
        for t in db.scalars(select(ActionTemplate).where(ActionTemplate.status == "approved"))
        if wf.applicable(t, item, project)
    ]
    if not wf.applicable(template, item, project) or len(candidates) != 1:
        return
    action_ids = list(
        db.scalars(
            select(ActionItem.id)
            .where(ActionItem.template_version_id == template.id)
            .order_by(ActionItem.sort_order, ActionItem.id)
        )
    )
    if action_ids:
        wf.link_actions(
            db,
            node,
            LinkInput(plan_item_id=item.id, plan_version_id=plan.id, template_item_ids=action_ids),
            request_id,
            source=source,
        )
