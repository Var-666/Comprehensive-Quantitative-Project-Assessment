from datetime import date, datetime, timedelta, timezone

from sqlalchemy import event, select
from test_action_matching import add_node, template
from test_workflow import ADMIN_ID, data, scan, setup_workflow

from app import workbench
from app.models import Milestone, PlanItem, ProjectMember
from conftest import REVIEWER_ID, VIEWER_ID, as_reviewer, login_as
from test_phase1 import create, node_payload


def recommendations(client):
    return data(client.get("/api/v1/workbench/next-actions"))


def all_actions(result):
    return [result["primary"], *result["secondary"]]


def test_empty_state_respects_creation_permission_and_requires_authentication(client):
    result = recommendations(client)
    assert result["primary"]["action_type"] == "create_project" and result["primary"]["actionable"]
    login_as(client, "viewer")
    result = recommendations(client)
    assert (
        result["primary"]["action_type"] == "request_access" and not result["primary"]["actionable"]
    )
    assert result["primary"]["target_path"] is None
    data(client.post("/api/v1/auth/logout"))
    assert client.get("/api/v1/workbench/next-actions").status_code == 401


def test_draft_recommendations_distinguish_editor_independent_reviewer_and_viewer(client):
    project, plan = create(client)
    node = data(add_node(client, project, plan), 201)
    result = recommendations(client)
    assert result["primary"]["reason_code"] == "MATCHING_MISSING"
    assert not any(r["action_type"] == "approve_plan" for r in all_actions(result))
    with as_reviewer(client):
        result = recommendations(client)
        assert (
            result["primary"]["action_type"] == "approve_plan" and result["primary"]["actionable"]
        )
        assert plan["id"] in result["primary"]["target_path"]
    data(
        client.put(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": VIEWER_ID, "role_code": "viewer"},
        )
    )
    login_as(client, "viewer")
    result = recommendations(client)
    assert all(not r["actionable"] for r in all_actions(result))
    assert node["id"] not in str(result["primary"]["target_path"])


def test_multiple_candidates_are_a_blocker_never_an_automatic_choice(client):
    project, plan = create(client)
    template(client)
    template(client, code="AT-SECOND")
    node = data(add_node(client, project, plan), 201)
    result = recommendations(client)
    assert result["primary"]["reason_code"] == "MATCHING_CONFLICT"
    assert node["id"] in result["primary"]["target_path"]
    assert "不会" not in result["primary"]["title"]


def test_due_assigned_tasks_precede_configuration_and_review_is_independent(
    client, factory, monkeypatch
):
    project, *_ = setup_workflow(client, action_count=2)
    data(scan(client, project))
    tasks = data(client.get("/api/v1/tasks"))["items"]
    for task in tasks:
        task.update(
            data(
                client.patch(
                    f"/api/v1/tasks/{task['id']}",
                    headers={"If-Match": str(task["row_version"])},
                    json={"assignee_id": ADMIN_ID, "reason": "明确执行人"},
                )
            )
        )
    data(
        client.post(
            f"/api/v1/tasks/{tasks[0]['id']}/feedback",
            headers={"If-Match": str(tasks[0]["row_version"])},
            json={
                "comment": "待独立核实",
                "evidence_ref": "已准备资料",
                "claimed_completion": True,
            },
        ),
        201,
    )
    monkeypatch.setattr(workbench, "now", lambda: datetime(2026, 10, 27, tzinfo=timezone.utc))
    result = recommendations(client)
    assert (
        result["primary"]["action_type"] == "execute_task" and result["primary"]["priority"] == 10
    )
    assert tasks[1]["id"] in result["primary"]["target_path"]
    assert not any(r["action_type"] == "verify_feedback" for r in all_actions(result))
    with as_reviewer(client):
        result = recommendations(client)
        assert result["primary"]["action_type"] == "verify_feedback"
        assert tasks[0]["id"] in result["primary"]["target_path"]
        assert not any(r["action_type"] == "execute_task" for r in all_actions(result))


def test_ready_flow_has_no_fabricated_task_and_role_revocation_is_immediate(client, factory):
    project, *_ = setup_workflow(client)
    result = recommendations(client)
    assert result["primary"]["action_type"] == "automatic_ready"
    assert not result["primary"]["actionable"] and result["secondary"] == []
    login_as(client, "reviewer")
    with factory.begin() as db:
        member = db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project["id"], ProjectMember.user_id == REVIEWER_ID
            )
        )
        member.active = False
    result = recommendations(client)
    assert result["primary"]["project_id"] is None and result["projects"] == []
    assert project["project_code"] not in str(result)


def test_queries_are_read_only_and_do_not_grow_per_node(client, factory):
    project, plan = create(client)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", capture)
    try:
        recommendations(client)
        baseline = len(statements)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    with factory.begin() as db:
        nodes = [
            Milestone(
                project_id=project["id"],
                milestone_code=f"N-{i}",
                milestone_name="图纸评审",
                node_type_code="设计资料",
            )
            for i in range(100)
        ]
        db.add_all(nodes)
        db.flush()
        db.add_all(
            [
                PlanItem(
                    milestone_id=n.id,
                    **{
                        k: v
                        for k, v in node_payload(plan["id"], n.milestone_code).items()
                        if k not in ("milestone_code", "planned_date")
                    },
                    planned_date=date(2026, 10, 26),
                )
                for n in nodes
            ]
        )
    statements.clear()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = recommendations(client)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) <= baseline + 1 and len(statements) < 25
    assert not any(
        s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements
    )
    assert result == recommendations(client)
    assert len(result["secondary"]) <= 2


def test_verified_tasks_lead_to_node_confirmation_then_evaluation(client, monkeypatch):
    from test_milestone_closure import complete, finish_task, state

    monkeypatch.setattr(workbench, "now", lambda: datetime(2026, 10, 27, tzinfo=timezone.utc))

    project, node, *_ = setup_workflow(client)
    data(scan(client, project))
    task = data(client.get("/api/v1/tasks"))["items"][0]
    finish_task(client, task)
    with as_reviewer(client):
        result = recommendations(client)
        assert result["primary"]["action_type"] == "confirm_milestone"
        assert result["primary"]["actionable"] and task["id"] in result["primary"]["target_path"]
        progress = state(client, task)
        data(complete(client, task, progress["row_version"]))
        result = recommendations(client)
        assert result["primary"]["action_type"] == "evaluate"


def test_empty_effective_plan_is_not_misreported_as_reminder_ready(client):
    from test_plan_deltas import activate

    project, plan = create(client)
    activate(client, project, plan)
    result = recommendations(client)
    assert result["primary"]["reason_code"] == "EFFECTIVE_PLAN_EMPTY"
    assert result["primary"]["actionable"]


def test_future_verified_date_does_not_claim_current_completion(client, factory):
    from app.models import ActualRecord

    project, node, *_ = setup_workflow(client)
    today = workbench.now().astimezone(timezone.utc).date()
    with factory.begin() as db:
        db.add(
            ActualRecord(
                milestone_id=node["id"],
                completion_flag=True,
                actual_date=today + timedelta(days=10),
                verification_status="verified",
                is_current=True,
                evidence_ref="需核对未来日期",
                submitted_by="earlier-compiler",
            )
        )
    result = recommendations(client)
    assert result["primary"]["reason_code"] == "ACTUAL_DATE_AFTER_TODAY"
    assert not any(r["action_type"] == "evaluate" for r in all_actions(result))
