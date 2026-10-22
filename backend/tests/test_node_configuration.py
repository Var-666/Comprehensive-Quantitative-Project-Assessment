from datetime import date, timedelta
import json

from sqlalchemy import delete, func, select, text
from test_action_matching import add_node, preview_import, template
from test_phase1 import commit, create, excel, node_payload
from test_plan_deltas import activate, edit, new_plan
from test_workflow import approval, data, scan

from app.models import Credential, Milestone, PlanItem, uid
from app.workflow_models import ActionLink, CalendarDay, Notification, WorkCalendar
from conftest import VIEWER_ID, as_reviewer, login_as


def check(client, node, plan):
    return data(
        client.get(
            f"/api/v1/milestones/{node['id']}/configuration-check",
            params={"plan_version_id": plan["id"]},
        )
    )


def rule(client, approved=True, **values):
    obj = data(
        client.post(
            "/api/v1/reminder-rules",
            json={
                "rule_code": "RR-READINESS",
                "version_label": "V1",
                "node_type_code": "设计资料",
                "source_ref": "经核对的提醒要求",
                "days_before": 7,
                "day_basis": "calendar_day",
                "recipient_role_code": "admin",
                **values,
            },
        ),
        201,
    )
    return approval(client, "reminder-rules", obj) if approved else obj


def test_configuration_checks_plan_rules_recipients_and_never_generates_on_reads(client, factory):
    project, plan = create(client)
    template(client)
    node = data(add_node(client, project, plan), 201)
    assert node["configuration"]["status"] == "reminder_missing"
    draft = rule(client, approved=False)
    assert check(client, node, plan)["status"] == "reminder_approval"
    rule_obj = approval(client, "reminder-rules", draft)
    state = check(client, node, plan)
    assert state["status"] == "ready" and state["ready"]
    assert state["plan"]["status"] == "draft" and not state["plan"]["can_approve"]
    assert state["reminders"]["rules"][0]["trigger_date"] == "2026-10-19"
    assert state["reminders"]["rules"][0]["recipient_count"] == 1
    with as_reviewer(client):
        assert check(client, node, plan)["plan"]["can_approve"]
    assert not any(row["eligible"] for row in data(scan(client, project))["items"])
    with factory.begin() as db:
        db.get(
            Credential, db.scalar(select(Credential.id).where(Credential.username == "admin"))
        ).enabled = False
    # Reviewer still has read access and can see why the configured recipient is unavailable.
    login_as(client, "reviewer")
    state = check(client, node, plan)
    assert state["status"] == "reminder_blocked"
    assert "账号" in state["reminders"]["rules"][0]["reason"]
    assert state["reminders"]["rules"][0]["id"] == rule_obj["id"]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Notification)) == 0


def test_workday_check_reports_incomplete_out_of_range_and_retired_calendars(client, factory):
    project, plan = create(client)
    template(client)
    node = data(add_node(client, project, plan), 201)
    start = date(2026, 10, 1)
    calendar = data(
        client.post(
            "/api/v1/work-calendars",
            json={
                "calendar_code": "CAL-READINESS",
                "version_label": "V1",
                "source_ref": "企业日历验收",
                "start_date": start.isoformat(),
                "end_date": "2026-10-31",
                "days": [
                    {"calendar_date": (start + timedelta(days=i)).isoformat(), "is_workday": True}
                    for i in range(31)
                ],
            },
        ),
        201,
    )
    approval(client, "work-calendars", calendar)
    rule(client, day_basis="workday", calendar_id=calendar["id"])
    assert check(client, node, plan)["reminders"]["rules"][0]["trigger_date"] == "2026-10-19"
    with factory.begin() as db:
        db.execute(
            delete(CalendarDay).where(
                CalendarDay.calendar_id == calendar["id"],
                CalendarDay.calendar_date == date(2026, 10, 25),
            )
        )
    assert "缺少" in check(client, node, plan)["reminders"]["rules"][0]["reason"]
    with factory.begin() as db:
        db.get(WorkCalendar, calendar["id"]).start_date = date(2026, 10, 26)
    assert "未覆盖" in check(client, node, plan)["reminders"]["rules"][0]["reason"]
    with factory.begin() as db:
        db.get(WorkCalendar, calendar["id"]).status = "retired"
    assert "未批准" in check(client, node, plan)["reminders"]["rules"][0]["reason"]


def test_tracking_only_persists_through_versions_and_respects_permissions(client, factory):
    project, plan = create(client)
    obj = template(client)
    node = data(
        client.post(
            f"/api/v1/projects/{project['id']}/milestones",
            json={
                **node_payload(plan["id"]),
                "tracking_only": True,
            },
        ),
        201,
    )
    assert node["configuration"]["status"] == "tracking_only"
    assert node["configuration"]["ready"]
    assert node["configuration"]["reminders"]["status"] == "not_required"
    rule(client)
    assert (
        client.post(
            f"/api/v1/milestones/{node['id']}/action-links",
            json={
                "plan_item_id": node["plan_item"]["id"],
                "template_item_ids": [obj["items"][0]["id"]],
            },
        ).status_code
        == 409
    )
    activate(client, project, plan)
    assert data(scan(client, project))["items"][0]["skipped_reason"] == "TRACKING_ONLY"
    metrics = data(
        client.get(
            f"/api/v1/projects/{project['id']}/metrics",
            params={"as_of": "2026-10-22", "plan_version_id": plan["id"]},
        )
    )
    assert metrics["counts"]["due_total"] == 1
    assert metrics["counts"]["pending_verification"] == 1
    assert (
        data(client.get("/api/v1/workbench/next-actions"))["projects"][0]["stage"] == "节点进展跟踪"
    )
    revision = new_plan(client, project)
    state = check(client, node, revision)
    assert state["tracking_only"] and state["status"] == "tracking_only"
    workbench = data(client.get("/api/v1/workbench/next-actions"))
    assert not any(
        "标准动作配置" in r["title"]
        for r in [workbench["primary"], *workbench["secondary"]]
        if r.get("project_id") == project["id"]
    )
    assert (
        client.patch(
            f"/api/v1/milestones/{node['id']}/plan-item",
            headers={"If-Match": str(node["row_version"])},
            json=node_payload(plan["id"]),
        ).status_code
        == 409
    )
    data(
        client.put(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": VIEWER_ID, "role_code": "viewer"},
        )
    )
    login_as(client, "viewer")
    assert not check(client, node, revision)["actions"]["can_modify"]
    assert (
        client.post(
            f"/api/v1/projects/{project['id']}/milestones",
            json=node_payload(revision["id"], "N-002"),
        ).status_code
        == 403
    )
    login_as(client)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ActionLink)) == 0
        assert db.scalar(select(func.count()).select_from(PlanItem)) == 1


def test_status_filter_counts_before_pagination_and_conflicts_remain_manual(client):
    project, plan = create(client)
    template(client)
    first = data(add_node(client, project, plan), 201)
    template(client, code="AT-SECOND")
    second = data(add_node(client, project, plan, "N-002"), 201)
    assert second["configuration"]["status"] == "actions_conflict"
    assert second["configuration"]["actions"]["action_count"] == 0
    url = f"/api/v1/projects/{project['id']}/milestones"
    filtered = data(
        client.get(
            url,
            params={
                "plan_version_id": plan["id"],
                "configuration_status": "actions_conflict",
                "page_size": 1,
            },
        )
    )
    assert filtered["total"] == 1 and filtered["items"][0]["id"] == second["id"]
    assert filtered["items"][0]["configuration"]["plan"]["status"] == "draft"
    assert (
        data(
            client.get(
                url,
                params={"plan_version_id": plan["id"], "configuration_status": "reminder_missing"},
            )
        )["items"][0]["id"]
        == first["id"]
    )
    assert client.get(url, params={"configuration_status": "fake"}).status_code == 422


def test_import_preview_counts_read_only_and_commit_reports_real_matching_results(client, factory):
    project, plan = create(client)
    template(client)
    batch = preview_import(client, project, plan)
    assert batch["matching_summary"]["automatic"] == 2
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PlanItem)) == 0
    template(client, code="AT-LATER")
    result = data(commit(client, batch))["result_json"]
    assert result["matching_summary"]["conflict"] == 2
    assert result["matching_summary"]["automatic"] == 0
    assert all(row["status"] == "conflict" for row in result["node_results"])
    assert all(row["configuration_status"] == "actions_conflict" for row in result["node_results"])
    assert data(commit(client, batch))["result_json"] == result


def test_import_explicit_tracking_only_does_not_auto_link(client, factory):
    project, plan = create(client)
    template(client)
    mapping = {
        "milestone_code": "节点编号",
        "milestone_name": "节点名称",
        "node_type_code": "节点类型",
        "planned_date": "计划完成日期",
        "tracking_only": "仅时间记录",
    }
    batch = data(
        client.post(
            "/api/v1/imports/preview",
            files={
                "file": (
                    "tracking.xlsx",
                    excel(
                        [["N-TIME", "仅记录日期", "设计资料", "2026-10-26", "是"]],
                        list(mapping.values()),
                    ),
                )
            },
            data={
                "target": "milestones",
                "project_id": project["id"],
                "plan_version_id": plan["id"],
                "mapping_json": json.dumps(mapping),
            },
        ),
        201,
    )
    assert batch["matching_summary"]["tracking_only"] == 1
    result = data(commit(client, batch))["result_json"]
    assert result["matching_summary"]["tracking_only"] == 1
    assert result["node_results"][0]["configuration_status"] == "tracking_only"
    with factory() as db:
        assert db.scalar(select(PlanItem.tracking_only)) is True
        assert db.scalar(select(func.count()).select_from(ActionLink)) == 0


def test_source_required_for_readiness_and_tracking_choice_changes_only_new_snapshot(
    client, factory
):
    project, first = create(client)
    template(client)
    rule(client)
    node = data(
        client.post(
            f"/api/v1/projects/{project['id']}/milestones",
            json={
                **node_payload(first["id"]),
                "tracking_only": True,
            },
        ),
        201,
    )
    activate(client, project, first)
    second = new_plan(client, project)
    updated = edit(client, node, second, tracking_only=False, source_ref=None)
    assert check(client, updated, second)["status"] == "actions_pending"
    matching = check(client, updated, second)["actions"]
    data(
        client.post(
            f"/api/v1/milestones/{node['id']}/action-links",
            json={
                "plan_item_id": updated["plan_item"]["id"],
                "plan_version_id": second["id"],
                "template_item_ids": [matching["candidates"][0]["items"][0]["id"]],
            },
        )
    )
    assert check(client, updated, second)["status"] == "source_missing"
    assert check(client, updated, first)["status"] == "tracking_only"
    with factory() as db:
        versions = {i.plan_version_id: i.tracking_only for i in db.scalars(select(PlanItem))}
        assert versions == {first["id"]: True, second["id"]: False}


def test_explicit_tracking_choice_in_restored_draft_preserves_old_actions_and_facts(
    client, factory
):
    project, first = create(client)
    template(client)
    node = data(add_node(client, project, first), 201)
    activate(client, project, first)
    second = new_plan(client, project)
    updated = edit(client, node, second, planned_date="2026-10-28")
    activate(client, project, second)
    restored = new_plan(client, project, base=first["id"])
    result = client.patch(
        f"/api/v1/milestones/{node['id']}/plan-item",
        headers={"If-Match": str(updated["row_version"])},
        json={
            **node_payload(restored["id"]),
            "tracking_only": True,
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["data"]["configuration"]["status"] == "tracking_only"
    assert result.json()["data"]["configuration"]["actions"]["action_count"] == 0
    assert result.json()["data"]["configuration"]["actions"]["links"]
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(PlanItem)
                .where(PlanItem.plan_version_id == restored["id"])
            )
            == 1
        )
        assert (
            db.scalar(select(PlanItem.tracking_only).where(PlanItem.plan_version_id == first["id"]))
            is False
        )
        assert db.scalar(select(func.count()).select_from(ActionLink)) == 3
    activate(client, project, restored)
    assert data(scan(client, project))["items"][0]["skipped_reason"] == "TRACKING_ONLY"


def test_tracking_choice_keeps_existing_links_and_can_be_reversed_explicitly_in_draft(
    client, factory
):
    project, plan = create(client)
    template(client)
    node = data(add_node(client, project, plan), 201)
    with factory() as db:
        original = [
            (link.id, link.snapshot_json, link.status) for link in db.scalars(select(ActionLink))
        ]
    updated = edit(client, node, plan, tracking_only=True)
    assert updated["configuration"]["status"] == "tracking_only"
    assert updated["configuration"]["actions"]["action_count"] == 0
    restored = edit(client, updated, plan, tracking_only=False)
    assert restored["configuration"]["actions"]["action_count"] == 1
    with factory() as db:
        assert [
            (link.id, link.snapshot_json, link.status) for link in db.scalars(select(ActionLink))
        ] == original


def test_raw_legacy_insert_defaults_to_regular_tracking_in_current_schema(client, factory):
    project, plan = create(client)
    source = data(add_node(client, project, plan), 201)
    with factory.begin() as db:
        legacy = Milestone(
            project_id=project["id"],
            milestone_code="LEGACY",
            milestone_name="历史导入节点",
            node_type_code="设计资料",
        )
        db.add(legacy)
        db.flush()
        item_id = uid()
        db.execute(
            text("""INSERT INTO milestone_plan_items
            (id,milestone_id,plan_version_id,milestone_name,node_type_code,planned_date,date_kind,change_reason,is_included)
            SELECT :item,:node,plan_version_id,milestone_name,node_type_code,planned_date,date_kind,change_reason,is_included
            FROM milestone_plan_items WHERE id=:source"""),
            {"item": item_id, "node": legacy.id, "source": source["plan_item"]["id"]},
        )
        assert db.get(PlanItem, item_id).tracking_only is False
