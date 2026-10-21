"""The overview must show scoped evidence, never prototype numbers or invented history."""

from sqlalchemy import func, select
from test_workflow import data, scan, setup_workflow

from app.models import AuditEvent
from conftest import as_reviewer, login_as
from test_phase1 import create, node_payload


def test_dashboard_empty_history_is_zero_and_read_only(client, factory):
    with factory() as db:
        before = db.scalar(select(func.count()).select_from(AuditEvent))
    result = data(client.get("/api/v1/metrics/dashboard?as_of=2026-10-19"))
    assert [m["month"] for m in result["months"]] == [
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
    ]
    assert all(m["due_total"] == 0 for m in result["months"])
    assert result["projects"] == [] and result["upcoming_tasks"] == []
    assert result["pending_tasks"] == 0
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == before
    assert client.get("/api/v1/metrics/dashboard?as_of=0001-01-01").status_code == 422


def test_dashboard_month_end_does_not_count_a_later_actual_or_unapproved_plan(client):
    project, plan = create(client)
    node = data(
        client.post(
            f"/api/v1/projects/{project['id']}/milestones",
            json={**node_payload(plan["id"]), "planned_date": "2026-09-30"},
        ),
        201,
    )
    before = data(client.get("/api/v1/metrics/dashboard?as_of=2026-10-19"))
    assert before["projects"][0]["counts"] is None
    assert all(m["due_total"] == 0 for m in before["months"])
    version = data(client.get(f"/api/v1/projects/{project['id']}/plan-versions"))[0]
    with as_reviewer(client):
        data(
            client.post(
                f"/api/v1/plan-versions/{plan['id']}/activate",
                headers={"If-Match": str(version["row_version"])},
                json={"approval_ref": "模拟独立批准"},
            )
        )
    actual = data(
        client.post(
            f"/api/v1/milestones/{node['id']}/actuals",
            json={
                "actual_date": "2026-10-02",
                "completion_flag": True,
                "evidence_ref": "模拟跨月完成",
            },
        ),
        201,
    )
    with as_reviewer(client):
        data(
            client.post(
                f"/api/v1/milestone-actuals/{actual['id']}/verify",
                json={"decision": "verified", "comment": "模拟独立核实"},
            )
        )
    result = data(client.get("/api/v1/metrics/dashboard?as_of=2026-10-19"))
    assert result["counts"]["late_completed"] == 1
    september = result["months"][-1]
    assert september["due_total"] == 1
    assert september["late_completed"] == 0 and september["pending_verification"] == 1
    assert "当前生效计划" in result["trend_basis"]


def test_dashboard_tasks_and_metrics_cannot_escape_project_scope(client):
    project, *_ = setup_workflow(client)
    data(scan(client, project))
    result = data(client.get("/api/v1/metrics/dashboard?as_of=2026-10-19"))
    assert result["pending_tasks"] == 1
    assert len(result["upcoming_tasks"]) == 1
    assert result["upcoming_tasks"][0]["project_id"] == project["id"]
    login_as(client, "viewer")
    result = data(client.get("/api/v1/metrics/dashboard?as_of=2026-10-19"))
    assert result["projects"] == [] and result["counts"]["total_nodes"] == 0
    assert result["upcoming_tasks"] == [] and result["pending_tasks"] == 0
    assert all(m["due_total"] == 0 for m in result["months"])
    client.cookies.clear()
    assert client.get("/api/v1/metrics/dashboard?as_of=2026-10-19").status_code == 401
