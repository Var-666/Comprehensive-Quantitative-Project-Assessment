from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from test_workflow import ADMIN_ID, data, scan, setup_workflow

from app.models import ActualRecord, AuditEvent, Milestone, Project
from app.workflow_models import Reminder, Task
from conftest import as_reviewer


def finish_task(client, task):
    path = f"/api/v1/tasks/{task['id']}"
    assigned = data(
        client.patch(
            path,
            headers={"If-Match": str(task["row_version"])},
            json={
                "assignee_id": ADMIN_ID,
                "reason": "分派标准动作",
            },
        )
    )
    feedback = data(
        client.post(
            path + "/feedback",
            headers={"If-Match": str(assigned["row_version"])},
            json={
                "comment": "动作已完成",
                "claimed_completion": True,
                "evidence_ref": f"凭证：{task['title']}",
            },
        ),
        201,
    )
    with as_reviewer(client):
        data(
            client.post(
                f"/api/v1/task-feedback/{feedback['id']}/verify",
                json={
                    "decision": "accepted",
                    "comment": "已核实动作与凭证",
                },
            )
        )
    return feedback["id"]


def state(client, task):
    return data(client.get(f"/api/v1/tasks/{task['id']}"))["milestone_completion"]


def complete(client, task, version, **changes):
    return client.post(
        f"/api/v1/tasks/{task['id']}/complete-milestone",
        headers={"If-Match": str(version)},
        json={"actual_date": "2026-10-25", "confirmed": True, **changes},
    )


def test_all_three_tasks_offer_one_confirmation_without_duplicate_evidence_or_review(
    client, factory
):
    p, node, *_ = setup_workflow(client, action_count=3)
    data(scan(client, p))
    tasks = data(client.get("/api/v1/tasks"))["items"]
    assert state(client, tasks[0])["total_tasks"] == 3
    feedback_ids = [finish_task(client, t) for t in tasks[:2]]
    with as_reviewer(client):
        progress = state(client, tasks[0])
        assert progress["completed_tasks"] == 2 and not progress["ready"]
        assert complete(client, tasks[0], progress["row_version"]).status_code == 409
    feedback_ids.append(finish_task(client, tasks[2]))
    progress = state(client, tasks[0])
    assert progress["ready"] and not progress["can_confirm"]
    assert complete(client, tasks[0], progress["row_version"]).status_code == 403
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ActualRecord)) == 0
    with as_reviewer(client):
        progress = state(client, tasks[0])
        assert progress["can_confirm"]
        assert (
            complete(client, tasks[0], progress["row_version"], confirmed=False).status_code == 422
        )
        assert (
            complete(client, tasks[0], progress["row_version"], actual_date="").status_code == 422
        )
        assert complete(client, tasks[0], progress["row_version"] + 1).status_code == 409
        for _ in range(2):
            data(complete(client, tasks[0], progress["row_version"]))
        assert (
            complete(
                client, tasks[0], progress["row_version"], actual_date="2026-10-24"
            ).status_code
            == 409
        )
        assert state(client, tasks[0])["actual_date"] == "2026-10-25"
    detail = data(client.get(f"/api/v1/milestones/{node['id']}"))
    actual = detail["current_actual"]
    assert actual["verification_status"] == "verified" and actual["completion_flag"]
    assert all(i in actual["comment"] for i in feedback_ids)
    assert all(f"凭证：{t['title']}" in actual["comment"] for t in tasks)
    assert data(scan(client, p))["items"][0]["skipped_reason"] == "VERIFIED_COMPLETED"
    assert (
        data(client.get("/api/v1/metrics/summary?as_of=2026-10-26"))["counts"]["on_time_completed"]
        == 1
    )
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ActualRecord)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "complete_milestone_from_tasks")
            )
            == 1
        )


@pytest.mark.parametrize(
    "blocked",
    ["missing_action", "cancelled_task", "source_invalidated", "pending_actual", "old_plan"],
)
def test_completion_rechecks_current_sources_and_pending_records(client, factory, blocked):
    p, node, *_ = setup_workflow(client, action_count=2)
    data(scan(client, p))
    tasks = data(client.get("/api/v1/tasks"))["items"]
    task = tasks[0]
    finish_task(client, task)
    if blocked != "missing_action":
        finish_task(client, tasks[1])
    with factory.begin() as db:
        if blocked == "missing_action":
            db.delete(db.get(Task, tasks[1]["id"]))
        elif blocked == "cancelled_task":
            db.get(Task, task["id"]).status = "cancelled"
        elif blocked == "source_invalidated":
            db.get(Reminder, task["reminder_instance_id"]).status = "invalidated"
        elif blocked == "pending_actual":
            db.add(
                ActualRecord(
                    milestone_id=node["id"],
                    completion_flag=True,
                    actual_date=date(2026, 10, 25),
                    evidence_ref="已有待审凭证",
                )
            )
        else:
            db.get(Project, p["id"]).current_plan_version_id = None
    with as_reviewer(client):
        progress = state(client, task)
        assert not progress["ready"] and not progress["can_confirm"]
        assert complete(client, task, progress["row_version"]).status_code == 409
    assert data(client.get(f"/api/v1/milestones/{node['id']}"))["current_actual"] is None


def test_feedback_submitter_cannot_close_even_with_review_role_and_failure_rolls_back(
    client, factory
):
    p, node, *_ = setup_workflow(client)
    data(scan(client, p))
    task = data(client.get("/api/v1/tasks"))["items"][0]
    finish_task(client, task)
    progress = state(client, task)
    # The admin has review permission, so this checks separation of duties rather than just role checks.
    assert complete(client, task, progress["row_version"]).status_code == 403
    with as_reviewer(client):
        progress = state(client, task)
        with patch("app.workflow.invalidate", side_effect=RuntimeError("rollback closure")):
            with pytest.raises(RuntimeError, match="rollback closure"):
                complete(client, task, progress["row_version"])
        assert state(client, task)["ready"]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ActualRecord)) == 0
        assert db.get(Milestone, node["id"]).row_version == progress["row_version"]
