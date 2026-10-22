from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from test_plan_deltas import activate, new_plan
from test_workflow import approval, data, template_payload

from app import action_matching
from app import services as svc
from app.models import AuditEvent, ImportBatch, Milestone, PlanItem
from app.workflow_models import ActionLink, Notification, Reminder, Task
from conftest import VIEWER_ID, as_reviewer, login_as
from test_phase1 import commit, create, excel, node_payload, payload


def template(client, code="AT-AUTO", status="approved", **values):
    obj = data(
        client.post(
            "/api/v1/action-templates", json={**template_payload(), "template_code": code, **values}
        ),
        201,
    )
    if status == "approved":
        obj = approval(client, "action-templates", obj)
        obj = data(client.get(f"/api/v1/action-templates/{obj['id']}"))
    elif status == "pending_review":
        obj = data(
            client.post(
                f"/api/v1/action-templates/{obj['id']}/submit-review",
                headers={"If-Match": str(obj["row_version"])},
            )
        )
    return obj


def add_node(client, project, plan, code="N-001"):
    return client.post(
        f"/api/v1/projects/{project['id']}/milestones",
        json={**node_payload(plan["id"], code, "2026-10-26"), "source_ref": "已核对计划来源"},
    )


def match(client, node, plan):
    return data(
        client.get(f"/api/v1/milestones/{node['id']}/action-matching?plan_version_id={plan['id']}")
    )


@pytest.mark.parametrize(
    "status,expected",
    [(None, "missing"), ("draft", "pending_approval"), ("pending_review", "pending_approval")],
)
def test_no_approved_template_never_creates_associations_or_tasks(
    client, factory, status, expected
):
    project, plan = create(client)
    if status:
        template(client, status=status)
    node = data(add_node(client, project, plan), 201)
    assert node["action_matching"]["status"] == expected
    assert node["configuration"]["status"] == ("actions_approval" if status else "actions_pending")
    with factory() as db:
        for model in (ActionLink, Reminder, Task, Notification):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def test_unique_template_links_all_actions_with_snapshot_source_and_audit(client, factory):
    project, plan = create(client)
    obj = template(
        client,
        items=[
            {
                **template_payload()["items"][0],
                "default_department_id": "00000000-0000-0000-0000-000000000001",
            }
        ],
    )
    node = data(add_node(client, project, plan), 201)
    state = node["action_matching"]
    assert state["status"] == "automatic" and state["action_count"] == 1
    assert state["links"][0]["snapshot_json"]["version_label"] == obj["version_label"]
    assert state["links"][0]["source"] == "automatic_node_create"
    assert state["links"][0]["department_name"] == "项目部"
    assert state["candidates"][0]["title"] == obj["title"]
    assert state["links"][0]["snapshot_json"]["completion_criteria"] == "资料清单经复核"
    assert add_node(client, project, plan).status_code == 409
    assert match(client, node, plan)["status"] == "automatic"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ActionLink)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "auto_link_action")
            )
            == 1
        )
        for model in (Reminder, Task, Notification):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def test_conflicting_candidates_require_explicit_confirmation_and_keep_manual_source(
    client, factory
):
    project, plan = create(client)
    first = template(client)
    template(client, code="AT-OTHER")
    node = data(add_node(client, project, plan), 201)
    assert node["action_matching"]["status"] == "conflict"
    assert (
        node["action_matching"]["candidate_count"] == 2 and node["action_matching"]["links"] == []
    )
    body = {
        "plan_item_id": node["plan_item"]["id"],
        "plan_version_id": plan["id"],
        "template_item_ids": [first["items"][0]["id"]],
    }
    for _ in range(2):
        data(client.post(f"/api/v1/milestones/{node['id']}/action-links", json=body))
    assert match(client, node, plan)["status"] == "manual"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ActionLink)) == 1


def test_concurrent_create_is_atomic_and_no_duplicate_links(client, factory):
    project, plan = create(client)
    template(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: add_node(client, project, plan), range(2)))
    assert sorted(r.status_code for r in responses) == [201, 409]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Milestone)) == 1
        assert db.scalar(select(func.count()).select_from(ActionLink)) == 1


def test_historical_nodes_read_only_and_effective_snapshot_cannot_be_bound(client, factory):
    project, plan = create(client)
    node = data(add_node(client, project, plan), 201)
    obj = template(client)
    activate(client, project, plan)
    state = match(client, node, plan)
    assert not state["can_modify"] and state["action_count"] == 0
    assert (
        data(client.get(f"/api/v1/projects/{project['id']}/milestones"))["items"][0][
            "action_matching"
        ]["action_count"]
        == 0
    )
    assert (
        client.post(
            f"/api/v1/milestones/{node['id']}/action-links",
            json={
                "plan_item_id": node["plan_item"]["id"],
                "template_item_ids": [obj["items"][0]["id"]],
            },
        ).status_code
        == 422
    )
    draft = new_plan(client, project)
    with as_reviewer(client):
        assert not match(client, node, draft)["can_modify"]
        assert add_node(client, project, draft, "N-READONLY").status_code == 403
    data(
        client.put(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": VIEWER_ID, "role_code": "viewer"},
        )
    )
    login_as(client, "viewer")
    assert not match(client, node, draft)["can_modify"]
    assert add_node(client, project, draft, "N-VIEWER").status_code == 403
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ActionLink)) == 0


def test_inherited_automatic_links_are_not_duplicated_and_project_scope_changes_are_visible(
    client, factory
):
    project, root = create(client)
    template(client, applicability_json={"project_type": "船舶建造"})
    node = data(add_node(client, project, root), 201)
    activate(client, project, root)
    draft = new_plan(client, project)
    assert match(client, node, draft)["status"] == "automatic"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ActionLink)) == 1
        assert db.scalar(select(func.count()).select_from(PlanItem)) == 1
    project = data(client.get(f"/api/v1/projects/{project['id']}"))
    data(
        client.patch(
            f"/api/v1/projects/{project['id']}",
            headers={"If-Match": str(project["row_version"])},
            json={**payload(), "project_type": "桥梁工程"},
        )
    )
    assert match(client, node, draft)["status"] == "needs_review"
    with factory() as db:
        link = db.scalar(select(ActionLink))
        assert link.snapshot_json["template_code"] == "AT-AUTO"
        assert db.scalar(select(func.count()).select_from(ActionLink)) == 1


def test_retired_candidate_is_rechecked_under_lock_before_auto_linking(client, factory):
    project, plan = create(client)
    template(client)
    original = svc.get
    changed = False

    def retire_when_locked(db, model, key, lock=False):
        nonlocal changed
        obj = original(db, model, key, lock)
        if model.__name__ == "ActionTemplate" and lock and not changed:
            changed = True
            obj.status = "retired"
            db.flush()
        return obj

    with patch.object(action_matching.svc, "get", side_effect=retire_when_locked):
        node = data(add_node(client, project, plan), 201)
    assert node["action_matching"]["action_count"] == 0
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ActionLink)) == 0


def preview_import(client, project, plan):
    content = excel(
        [
            [project["project_code"], f"N-I{i}", "导入节点", "设计资料", "2026-10-26"]
            for i in range(2)
        ],
        ["项目编号", "节点编号", "节点名称", "节点类型", "计划完成日期"],
    )
    return data(
        client.post(
            "/api/v1/imports/preview",
            files={"file": ("auto.xlsx", content)},
            data={
                "target": "milestones",
                "project_id": project["id"],
                "plan_version_id": plan["id"],
                "mapping_json": '{"project_code":"项目编号","milestone_code":"节点编号","milestone_name":"节点名称","node_type_code":"节点类型","planned_date":"计划完成日期"}',
            },
        ),
        201,
    )


def test_import_preview_never_writes_and_confirm_auto_links_idempotently(client, factory):
    project, plan = create(client)
    template(client)
    batch = preview_import(client, project, plan)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ActionLink)) == 0
        assert db.scalar(select(func.count()).select_from(Milestone)) == 0
    data(commit(client, batch))
    data(commit(client, batch))
    with factory() as db:
        links = list(db.scalars(select(ActionLink)))
        assert len(links) == 2 and all(
            link.snapshot_json["link_source"] == "automatic_excel_import" for link in links
        )
        assert db.scalar(select(func.count()).select_from(Milestone)) == 2


def test_matching_failure_rolls_back_the_whole_import_batch(client, factory):
    project, plan = create(client)
    template(client)
    batch = preview_import(client, project, plan)
    original = action_matching.wf.link_actions
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            svc.fail(409, "MATCHING_WRITE_FAILED", "匹配写入失败")
        return original(*args, **kwargs)

    with patch.object(action_matching.wf, "link_actions", side_effect=fail_second):
        assert commit(client, batch).status_code == 409
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Milestone)) == 0
        assert db.scalar(select(func.count()).select_from(ActionLink)) == 0
        assert db.get(ImportBatch, batch["id"]).status == batch["status"]


def test_replacement_preserves_old_snapshots_and_new_draft_needs_manual_confirmation(
    client, factory
):
    project, root = create(client)
    template(client)
    node = data(add_node(client, project, root), 201)
    old_snapshot = node["action_matching"]["links"][0]["snapshot_json"]
    activate(client, project, root)
    replacement = template(client, version_label="V2", title="新版资料准备")
    assert match(client, node, root)["status"] == "needs_review"
    draft = new_plan(client, project)
    assert match(client, node, draft)["action_count"] == 0
    data(
        client.post(
            f"/api/v1/milestones/{node['id']}/action-links",
            json={
                "plan_item_id": node["plan_item"]["id"],
                "plan_version_id": draft["id"],
                "template_item_ids": [replacement["items"][0]["id"]],
            },
        )
    )
    current = match(client, node, draft)
    assert current["status"] == "manual" and current["action_count"] == 1
    with factory() as db:
        old = db.scalar(
            select(ActionLink).where(ActionLink.plan_item_id == node["plan_item"]["id"])
        )
        assert old.snapshot_json == old_snapshot and old.snapshot_json["version_label"] == "V1"
        assert old.status == "superseded"


def test_automatic_matching_waits_for_plan_rule_and_trigger_then_delivers_once(
    client, factory, monkeypatch
):
    from datetime import datetime, timezone

    from app import worker

    project, plan = create(client)
    template(client)
    node = data(add_node(client, project, plan), 201)
    assert node["action_matching"]["status"] == "automatic"
    rule = data(
        client.post(
            "/api/v1/reminder-rules",
            json={
                "rule_code": "RR-AUTO",
                "version_label": "V1",
                "node_type_code": "设计资料",
                "source_ref": "确认提前7天",
                "days_before": 7,
                "day_basis": "calendar_day",
                "recipient_role_code": "admin",
                "catch_up_days": 0,
            },
        ),
        201,
    )
    monkeypatch.setattr(worker, "now", lambda: datetime(2026, 10, 19, tzinfo=timezone.utc))
    assert worker.run_once(factory) == 0
    activate(client, project, plan)
    assert worker.run_once(factory) == 0
    approval(client, "reminder-rules", rule)
    monkeypatch.setattr(worker, "now", lambda: datetime(2026, 10, 18, tzinfo=timezone.utc))
    assert worker.run_once(factory) == 0
    monkeypatch.setattr(worker, "now", lambda: datetime(2026, 10, 19, tzinfo=timezone.utc))
    assert worker.run_once(factory) == 1
    assert worker.run_once(factory) == 0
    assert len(data(client.get("/api/v1/inbox"))) == 1
    tasks = data(client.get("/api/v1/tasks"))["items"]
    assert (
        len(tasks) == 1 and tasks[0]["assignee_id"] is None and tasks[0]["status"] == "unassigned"
    )


def test_changing_node_type_preserves_old_snapshot_and_requires_new_confirmation(client, factory):
    from app.models import NodeType

    project, plan = create(client)
    template(client)
    node = data(add_node(client, project, plan), 201)
    with factory.begin() as db:
        db.add(NodeType(code="设备验收", display_name="设备验收"))
    template(client, code="AT-EQUIPMENT", node_type_code="设备验收")
    data(
        client.patch(
            f"/api/v1/milestones/{node['id']}/plan-item",
            headers={"If-Match": str(node["row_version"])},
            json={
                **node_payload(plan["id"], planned="2026-10-26"),
                "node_type_code": "设备验收",
                "change_reason": "节点类型经人工复核调整",
            },
        )
    )
    current = match(client, node, plan)
    assert (
        current["status"] == "needs_review"
        and current["action_count"] == 0
        and current["candidate_count"] == 1
    )
    with factory() as db:
        links = list(db.scalars(select(ActionLink)))
        assert len(links) == 1 and links[0].status == "superseded"
        assert links[0].snapshot_json["template_code"] == "AT-AUTO"


def test_closed_project_does_not_gain_automatic_associations(client):
    project, plan = create(client)
    template(client)
    current = data(client.get(f"/api/v1/projects/{project['id']}"))
    data(
        client.patch(
            f"/api/v1/projects/{project['id']}",
            headers={"If-Match": str(current["row_version"])},
            json={**payload(), "project_status": "completed"},
        )
    )
    node = data(add_node(client, project, plan), 201)
    assert (
        node["action_matching"]["action_count"] == 0 and not node["action_matching"]["can_modify"]
    )
