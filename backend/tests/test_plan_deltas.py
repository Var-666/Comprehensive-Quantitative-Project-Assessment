from datetime import date, timedelta

from sqlalchemy import func, select
from test_milestone_closure import complete, finish_task, state
from test_workflow import approval, data, scan, setup_workflow, template_payload

from app.models import Milestone, PlanItem
from app.workflow_models import ActionLink, Task
from conftest import as_reviewer
from test_phase1 import create, node_payload


def new_plan(client, project, base=None):
    project = data(client.get(f"/api/v1/projects/{project['id']}"))
    return data(
        client.post(
            f"/api/v1/projects/{project['id']}/plan-versions",
            headers={"If-Match": str(project["row_version"])},
            json={"change_reason": "雨天调整计划", **({"base_version_id": base} if base else {})},
        ),
        201,
    )


def activate(client, project, plan):
    current = next(
        p
        for p in data(client.get(f"/api/v1/projects/{project['id']}/plan-versions"))
        if p["id"] == plan["id"]
    )
    with as_reviewer(client):
        return data(
            client.post(
                f"/api/v1/plan-versions/{plan['id']}/activate",
                headers={"If-Match": str(current["row_version"])},
                json={"approval_ref": "独立核对变更"},
            )
        )


def edit(client, node, plan, **values):
    return data(
        client.patch(
            f"/api/v1/milestones/{node['id']}/plan-item",
            headers={"If-Match": str(node["row_version"])},
            json={**node_payload(plan["id"], node["milestone_code"]), **values},
        )
    )


def test_thousand_nodes_and_ten_changes_store_only_ten_extra_rows(client, factory):
    project, root = create(client)
    with factory.begin() as db:
        nodes = [
            Milestone(
                project_id=project["id"],
                milestone_code=f"N-{i:04}",
                milestone_name="图纸评审",
                node_type_code="设计资料",
            )
            for i in range(1000)
        ]
        db.add_all(nodes)
        db.flush()
        db.add_all(
            [
                PlanItem(
                    milestone_id=n.id,
                    **{
                        k: v
                        for k, v in node_payload(root["id"], n.milestone_code).items()
                        if k not in ("milestone_code", "planned_date")
                    },
                    planned_date=date(2026, 10, 1),
                )
                for n in nodes
            ]
        )
        target_id = nodes[0].id
    activate(client, project, root)
    plan = root
    for i in range(10):
        plan = new_plan(client, project)
        with factory() as db:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(PlanItem)
                    .where(PlanItem.plan_version_id == plan["id"])
                )
                == 0
            )
        target = data(client.get(f"/api/v1/milestones/{target_id}?plan_version_id={plan['id']}"))
        updated = edit(
            client,
            target,
            plan,
            planned_date=(date(2026, 10, 1) + timedelta(days=2 * (i + 1))).isoformat(),
            change_reason=f"雨天顺延第{i + 1}次",
        )
        assert updated["plan_change"]["delta_days"] == 2
        changes = data(
            client.get(
                f"/api/v1/projects/{project['id']}/milestones?plan_version_id={plan['id']}&changes_only=true"
            )
        )
        assert changes["total"] == changes["change_total"] == 1
        assert changes["plan_total"] == 1000
        assert changes["items"][0]["id"] == target_id
        activate(client, project, plan)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PlanItem)) == 1010
        assert (
            db.scalar(
                select(func.count()).select_from(PlanItem).where(PlanItem.milestone_id != target_id)
            )
            == 999
        )
    assert data(client.get(f"/api/v1/projects/{project['id']}/milestones"))["total"] == 1000
    old = data(client.get(f"/api/v1/milestones/{target_id}?plan_version_id={root['id']}"))
    assert old["plan_item"]["planned_date"] == "2026-10-01"
    assert (
        data(client.get(f"/api/v1/projects/{project['id']}/metrics?as_of=2026-12-01"))["counts"][
            "total_nodes"
        ]
        == 1000
    )
    draft = new_plan(client, project)
    target = data(client.get(f"/api/v1/milestones/{target_id}?plan_version_id={draft['id']}"))
    edit(
        client,
        target,
        draft,
        planned_date=target["plan_item"]["planned_date"],
        change_reason=target["plan_item"]["change_reason"],
    )
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(PlanItem)
                .where(PlanItem.plan_version_id == draft["id"])
            )
            == 0
        )


def test_inherited_tasks_and_closure_survive_an_unchanged_plan_without_cloning(client, factory):
    project, node, *_ = setup_workflow(client)
    data(scan(client, project))
    task = data(client.get("/api/v1/tasks"))["items"][0]
    finish_task(client, task)
    draft = new_plan(client, project)
    activate(client, project, draft)
    assert data(scan(client, project))["generated"] == 0
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ActionLink)) == 1
        assert db.scalar(select(func.count()).select_from(PlanItem)) == 1
        assert db.get(Task, task["id"]).requires_review is False
    with as_reviewer(client):
        progress = state(client, task)
        assert progress["can_confirm"]
        data(complete(client, task, progress["row_version"]))
    assert data(client.get(f"/api/v1/milestones/{node['id']}"))["current_actual"]["completion_flag"]


def test_legacy_full_snapshots_remain_readable_and_unchanged_rows_are_not_marked(client, factory):
    project, root = create(client)
    node = data(
        client.post(f"/api/v1/projects/{project['id']}/milestones", json=node_payload(root["id"])),
        201,
    )
    activate(client, project, root)
    draft = new_plan(client, project)
    with factory.begin() as db:
        original = db.get(PlanItem, node["plan_item"]["id"])
        db.add(
            PlanItem(
                **{
                    c.name: getattr(original, c.name)
                    for c in PlanItem.__table__.columns
                    if c.name not in ("id", "plan_version_id")
                },
                plan_version_id=draft["id"],
            )
        )
    listed = data(
        client.get(f"/api/v1/projects/{project['id']}/milestones?plan_version_id={draft['id']}")
    )
    assert listed["total"] == 1 and listed["change_total"] == 0
    assert listed["items"][0]["plan_change"] is None


def test_restoring_an_old_base_creates_fresh_tasks_without_reviving_cancelled_history(
    client, factory
):
    project, node, *_ = setup_workflow(client)
    root = data(client.get(f"/api/v1/projects/{project['id']}/plan-versions"))[0]
    data(scan(client, project))
    old_task = data(client.get("/api/v1/tasks"))["items"][0]
    draft = new_plan(client, project)
    edit(
        client,
        data(client.get(f"/api/v1/milestones/{node['id']}?plan_version_id={draft['id']}")),
        draft,
        planned_date="2026-10-28",
        source_ref="原计划依据",
        change_reason="雨天后延",
    )
    activate(client, project, draft)
    restored = new_plan(client, project, root["id"])
    activate(client, project, restored)
    data(scan(client, project))
    tasks = data(client.get("/api/v1/tasks"))["items"]
    assert any(t["id"] != old_task["id"] and t["status"] == "unassigned" for t in tasks)
    with factory() as db:
        assert db.get(Task, old_task["id"]).status == "cancelled"


def test_binding_actions_in_an_inherited_draft_changes_only_that_node(client, factory):
    project, node, *_ = setup_workflow(client)
    draft = new_plan(client, project)
    template = data(
        client.post(
            "/api/v1/action-templates",
            json={
                **template_payload(),
                "template_code": "AT-ADDED",
            },
        ),
        201,
    )
    approval(client, "action-templates", template)
    original_id = node["plan_item"]["id"]
    data(
        client.post(
            f"/api/v1/milestones/{node['id']}/action-links",
            json={
                "plan_item_id": original_id,
                "plan_version_id": draft["id"],
                "template_item_ids": [template["items"][0]["id"]],
            },
        )
    )
    detail = data(client.get(f"/api/v1/milestones/{node['id']}?plan_version_id={draft['id']}"))
    assert detail["plan_item"]["id"] != original_id
    assert "actions" in detail["plan_change"]["fields"]
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ActionLink)
                .where(ActionLink.plan_item_id == original_id)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(ActionLink)
                .where(ActionLink.plan_item_id == detail["plan_item"]["id"])
            )
            == 2
        )
