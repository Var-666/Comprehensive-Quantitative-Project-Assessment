"""Phase two tests protect review boundaries, facts and deterministic generation."""

from datetime import date, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from app.models import ActualRecord
from app.workflow_models import (
    ActionLink,
    DeliveryAttempt,
    Feedback,
    InboxMessage,
    Notification,
    Reminder,
    Task,
)
from conftest import REVIEWER_ID, VIEWER_ID, as_reviewer, login_as
from test_phase1 import create, node_payload

ADMIN_ID = "00000000-0000-0000-0000-000000000002"


def data(response, status=200):
    assert response.status_code == status, response.text
    return response.json()["data"]


def approval(client, path, obj):
    submitted = data(
        client.post(
            f"/api/v1/{path}/{obj['id']}/submit-review",
            headers={"If-Match": str(obj["row_version"])},
        )
    )
    with as_reviewer(client):
        return data(
            client.post(
                f"/api/v1/{path}/{obj['id']}/review",
                headers={"If-Match": str(submitted["row_version"])},
                json={"decision": "approved", "approval_ref": "独立测试审核依据"},
            )
        )


def template_payload():
    return {
        "template_code": "AT-TEST",
        "version_label": "V1",
        "title": "资料准备",
        "node_type_code": "设计资料",
        "source_ref": "测试模板依据",
        "items": [
            {
                "item_code": "01",
                "title": "整理资料",
                "completion_criteria": "资料清单经复核",
                "materials_required_json": ["图纸清单"],
            }
        ],
    }


def setup_workflow(client, recipient="admin", catch_up=0, action_count=1):
    p, plan = create(client)
    node = data(
        client.post(
            f"/api/v1/projects/{p['id']}/milestones",
            json={**node_payload(plan["id"], planned="2026-10-26"), "source_ref": "已录入计划来源"},
        ),
        201,
    )
    payload = template_payload()
    payload["items"].extend(
        {**payload["items"][0], "item_code": str(i + 1), "title": f"整理资料{i + 1}"}
        for i in range(1, action_count)
    )
    template = data(client.post("/api/v1/action-templates", json=payload), 201)
    approval(client, "action-templates", template)
    links = data(
        client.post(
            f"/api/v1/milestones/{node['id']}/action-links",
            json={
                "plan_item_id": node["plan_item"]["id"],
                "template_item_ids": [i["id"] for i in template["items"]],
            },
        )
    )
    rule = data(
        client.post(
            "/api/v1/reminder-rules",
            json={
                "rule_code": "RR-TEST",
                "version_label": "V1",
                "node_type_code": "设计资料",
                "source_ref": "测试提醒规则依据",
                "days_before": 7,
                "day_basis": "calendar_day",
                "recipient_role_code": recipient,
                "catch_up_days": catch_up,
            },
        ),
        201,
    )
    rule = approval(client, "reminder-rules", rule)
    plan = client.get(f"/api/v1/projects/{p['id']}/plan-versions").json()["data"][0]
    with as_reviewer(client):
        data(
            client.post(
                f"/api/v1/plan-versions/{plan['id']}/activate",
                headers={"If-Match": str(plan["row_version"])},
                json={"approval_ref": "独立测试计划批准"},
            )
        )
    return p, node, template, rule, links


def scan(client, p, day="2026-10-19", generate=True):
    return client.post(
        "/api/v1/reminder-jobs/" + ("run" if generate else "simulate"),
        json={"as_of": day, "project_ids": [p["id"]]},
    )


def first_notice(client):
    return client.get("/api/v1/notifications").json()["data"]["items"][0]


def scan_legacy(client, project):
    # Reproduce pre-upgrade drafts to keep the historical editing/review contract covered.
    with patch("app.workflow.deliver"):
        return scan(client, project)


def submit_notice(client, notice):
    return data(
        client.post(
            f"/api/v1/notifications/{notice['id']}/submit-review",
            headers={"If-Match": str(notice["row_version"])},
        )
    )


def test_config_approval_immutability_and_safe_matching(client):
    """Unapproved generic templates must never become executable actions."""
    p, plan = create(client)
    t = data(client.post("/api/v1/action-templates", json=template_payload()), 201)
    node = data(
        client.post(f"/api/v1/projects/{p['id']}/milestones", json=node_payload(plan["id"])), 201
    )
    body = {"plan_item_id": node["plan_item"]["id"], "template_item_ids": [t["items"][0]["id"]]}
    assert (
        client.post(f"/api/v1/milestones/{node['id']}/action-links", json=body).status_code == 409
    )
    t = data(
        client.post(
            f"/api/v1/action-templates/{t['id']}/submit-review",
            headers={"If-Match": str(t["row_version"])},
        )
    )
    assert (
        client.post(
            f"/api/v1/action-templates/{t['id']}/review",
            headers={"If-Match": str(t["row_version"])},
            json={"decision": "approved", "approval_ref": "自审"},
        ).status_code
        == 403
    )
    with as_reviewer(client):
        t = data(
            client.post(
                f"/api/v1/action-templates/{t['id']}/review",
                headers={"If-Match": str(t["row_version"])},
                json={"decision": "approved", "approval_ref": "独立"},
            )
        )
    assert (
        client.patch(
            f"/api/v1/action-templates/{t['id']}",
            headers={"If-Match": str(t["row_version"])},
            json=template_payload(),
        ).status_code
        == 409
    )
    a = data(client.post(f"/api/v1/milestones/{node['id']}/action-links", json=body))
    b = data(client.post(f"/api/v1/milestones/{node['id']}/action-links", json=body))
    assert a[0]["id"] == b[0]["id"]
    bad = {
        **template_payload(),
        "template_code": "AT-BAD",
        "applicability_json": {"python": "eval()"},
    }
    assert client.post("/api/v1/action-templates", json=bad).status_code == 422


def test_natural_day_preview_and_generation_are_deterministic_idempotent(client, factory):
    """TC007: 26 Oct minus 7 natural days is 19 Oct; scanning twice adds no tasks."""
    p, node, _, _, _ = setup_workflow(client)
    preview = data(scan(client, p, generate=False))
    assert preview["items"][0]["trigger_date"] == "2026-10-19"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Reminder)) == 0
        assert db.scalar(select(func.count()).select_from(InboxMessage)) == 0
    assert data(scan(client, p))["generated"] == 1
    assert data(scan(client, p))["generated"] == 0
    assert (
        data(scan(client, p, "2026-10-20"))["items"][0]["skipped_reason"]
        == "OUTSIDE_TRIGGER_WINDOW"
    )
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Task)) == 1
        assert db.scalar(select(func.count()).select_from(Notification)) == 1
        assert db.scalar(select(func.count()).select_from(InboxMessage)) == 1
        assert db.scalar(select(func.count()).select_from(DeliveryAttempt)) == 1
        assert db.scalar(select(func.count()).select_from(ActualRecord)) == 0
    notice = first_notice(client)
    assert notice["status"] == "sent" and notice["reviews"] == []
    assert len(notice["deliveries"]) == 1
    assert len(data(client.get("/api/v1/inbox"))) == 1
    assert notice["fact_snapshot_json"]["generation_mode"] == "deterministic_template"
    assert notice["fact_snapshot_json"]["source_ref"] == "已录入计划来源"


def test_workday_requires_approved_explicit_enterprise_calendar(client):
    """TC017: weekends cannot silently replace an approved holiday/makeup calendar."""
    create(client)
    base = {"planned_date": "2026-10-28", "days_before": 3, "day_basis": "workday"}
    assert (
        data(client.post("/api/v1/reminder-rules/preview-trigger", json=base))["reason"]
        == "CALENDAR_NOT_APPROVED"
    )
    days = [
        {
            "calendar_date": (date(2026, 10, 19) + timedelta(days=i)).isoformat(),
            "is_workday": i not in (4, 6),
            "reason": "10月23休息、24调休工作，仅测试",
        }
        for i in range(10)
    ]
    body = {
        "calendar_code": "TEST-CAL",
        "version_label": "V1",
        "source_ref": "模拟日历，不是真实节假日",
        "start_date": "2026-10-19",
        "end_date": "2026-10-28",
        "days": days,
    }
    assert (
        client.post("/api/v1/work-calendars", json={**body, "days": days[:-1]}).status_code == 422
    )
    calendar = data(client.post("/api/v1/work-calendars", json=body), 201)
    assert (
        data(
            client.post(
                "/api/v1/reminder-rules/preview-trigger",
                json={**base, "calendar_id": calendar["id"]},
            )
        )["reason"]
        == "CALENDAR_NOT_APPROVED"
    )
    approval(client, "work-calendars", calendar)
    result = data(
        client.post(
            "/api/v1/reminder-rules/preview-trigger", json={**base, "calendar_id": calendar["id"]}
        )
    )
    assert (
        result["trigger_date"] == "2026-10-24"
    )  # Makeup Saturday counts; Friday was explicitly nonworking.
    assert (
        data(
            client.post(
                "/api/v1/reminder-rules/preview-trigger",
                json={**base, "calendar_id": calendar["id"], "days_before": 30},
            )
        )["reason"]
        == "CALENDAR_OUT_OF_RANGE"
    )


def test_legacy_notice_review_is_not_delivery_and_external_channels_are_disabled(client, factory):
    """Historical drafts retain their existing review and delivery contract."""
    p, _, _, _, _ = setup_workflow(client)
    data(scan_legacy(client, p))
    notice = submit_notice(client, first_notice(client))
    body = {"draft_version": notice["draft_version"], "decision": "approved", "comment": "内容确认"}
    url = f"/api/v1/notifications/{notice['id']}"
    assert (
        client.post(
            url + "/review", headers={"If-Match": str(notice["row_version"])}, json=body
        ).status_code
        == 403
    )
    with as_reviewer(client):
        assert (
            client.post(
                url + "/review",
                headers={"If-Match": str(notice["row_version"])},
                json={**body, "draft_version": 99},
            ).status_code
            == 409
        )
        notice = data(
            client.post(
                url + "/review", headers={"If-Match": str(notice["row_version"])}, json=body
            )
        )
    assert notice["status"] == "approved_pending_send" and notice["deliveries"] == []
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(InboxMessage)) == 0
    assert (
        client.patch(
            url + "/draft",
            headers={"If-Match": str(notice["row_version"])},
            json={"title": "改写", "body": "已审核后不可改"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            url + "/dispatch",
            headers={"If-Match": str(notice["row_version"])},
            json={"channel": "email"},
        ).status_code
        == 409
    )
    for _ in range(2):
        sent = data(
            client.post(
                url + "/dispatch",
                headers={"If-Match": str(notice["row_version"])},
                json={"channel": "in_app"},
            )
        )
        assert sent["status"] == "sent" and len(sent["deliveries"]) == 1
    inbox = data(client.get("/api/v1/inbox"))
    assert len(inbox) == 1
    data(client.post(f"/api/v1/inbox/{inbox[0]['id']}/read"))
    with as_reviewer(client):
        assert data(client.get("/api/v1/inbox")) == []
        assert client.post(f"/api/v1/inbox/{inbox[0]['id']}/read").status_code == 404


def test_task_execution_and_independent_verification_do_not_complete_node(client, factory):
    """A verified preparation task is not an actual milestone completion fact."""
    p, node, _, _, _ = setup_workflow(client)
    data(scan(client, p))
    task = data(client.get("/api/v1/tasks"))["items"][0]
    url = f"/api/v1/tasks/{task['id']}"
    task = data(
        client.patch(
            url,
            headers={"If-Match": str(task["row_version"])},
            json={"assignee_id": ADMIN_ID, "reason": "明确执行人"},
        )
    )
    feedback = data(
        client.post(
            url + "/feedback",
            headers={"If-Match": str(task["row_version"])},
            json={"comment": "已整理", "claimed_completion": True, "evidence_ref": "模拟材料清单"},
        ),
        201,
    )
    verify_url = f"/api/v1/task-feedback/{feedback['id']}/verify"
    assert (
        client.post(verify_url, json={"decision": "accepted", "comment": "自核实"}).status_code
        == 403
    )
    with as_reviewer(client):
        verified = data(
            client.post(verify_url, json={"decision": "accepted", "comment": "独立核实资料"})
        )
        assert verified["status"] == "verified_done"
        assert (
            client.post(
                verify_url, json={"decision": "accepted", "comment": "重复核实"}
            ).status_code
            == 409
        )
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ActualRecord)
                .where(ActualRecord.milestone_id == node["id"])
            )
            == 0
        )
        assert db.get(Feedback, feedback["id"]).submitted_by == ADMIN_ID
    assert data(client.get(url + "/audit-events"))


def test_version_change_invalidates_drafts_preserves_sent_history_and_rebinds(
    client, factory, monkeypatch
):
    """TC015: V3 never rewrites V2 notices, dates, actions or begun execution history."""
    from datetime import datetime, timezone

    from app import services

    # This scenario activates the new plan before its trigger date. A wall-clock
    # activation on 21 October would already scan it, making the later scan a replay.
    monkeypatch.setattr(services, "now", lambda: datetime(2026, 10, 19, 4, tzinfo=timezone.utc))
    p, node, _, _, _ = setup_workflow(client, catch_up=1)
    data(scan(client, p))
    task = data(client.get("/api/v1/tasks"))["items"][0]
    task = data(
        client.patch(
            f"/api/v1/tasks/{task['id']}",
            headers={"If-Match": str(task["row_version"])},
            json={"assignee_id": ADMIN_ID, "status": "in_progress", "reason": "开始执行"},
        )
    )
    old_notice = first_notice(client)
    p = data(client.get(f"/api/v1/projects/{p['id']}"))
    plan = data(
        client.post(
            f"/api/v1/projects/{p['id']}/plan-versions",
            headers={"If-Match": str(p["row_version"])},
            json={"change_reason": "计划调整"},
        ),
        201,
    )
    node = data(client.get(f"/api/v1/milestones/{node['id']}?plan_version_id={plan['id']}"))
    node = data(
        client.patch(
            f"/api/v1/milestones/{node['id']}/plan-item",
            headers={"If-Match": str(node["row_version"])},
            json={**node_payload(plan["id"], planned="2026-10-28"), "source_ref": "新版来源"},
        )
    )
    plan = data(client.get(f"/api/v1/projects/{p['id']}/plan-versions"))[0]
    with as_reviewer(client):
        data(
            client.post(
                f"/api/v1/plan-versions/{plan['id']}/activate",
                headers={"If-Match": str(plan["row_version"])},
                json={"approval_ref": "新版确认"},
            )
        )
    assert data(client.get(f"/api/v1/notifications/{old_notice['id']}"))["status"] == "sent"
    assert data(client.get(f"/api/v1/tasks/{task['id']}"))["requires_review"] is True
    assert data(scan(client, p, "2026-10-21"))["generated"] == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ActionLink)) == 2
        assert db.scalar(select(func.count()).select_from(Reminder)) == 2
    notices = data(client.get("/api/v1/notifications"))["items"]
    assert {n["fact_snapshot_json"]["planned_date"] for n in notices} == {
        "2026-10-26",
        "2026-10-28",
    }


def test_authorization_scopes_and_unassigned_execution_are_enforced(client):
    """Hidden controls cannot substitute for server-side permission and executor checks."""
    p, _, _, _, _ = setup_workflow(client)
    data(scan(client, p))
    task = data(client.get("/api/v1/tasks"))["items"][0]
    data(
        client.put(
            f"/api/v1/projects/{p['id']}/members",
            json={"user_id": VIEWER_ID, "role_code": "viewer"},
        )
    )
    login_as(client, "viewer")
    assert client.post("/api/v1/action-templates", json=template_payload()).status_code == 403
    assert scan(client, p).status_code == 403
    assert (
        client.patch(
            f"/api/v1/tasks/{task['id']}",
            headers={"If-Match": "1"},
            json={"assignee_id": VIEWER_ID, "reason": "自派"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/tasks/{task['id']}/feedback",
            headers={"If-Match": "1"},
            json={"comment": "未分派", "claimed_completion": True, "evidence_ref": "无"},
        ).status_code
        == 403
    )
    login_as(client)
    data(
        client.put(
            f"/api/v1/projects/{p['id']}/members",
            json={"user_id": VIEWER_ID, "role_code": "viewer", "active": False},
        )
    )
    login_as(client, "viewer")
    assert data(client.get("/api/v1/tasks"))["total"] == 0
    assert client.get(f"/api/v1/tasks/{task['id']}").status_code == 404


def test_rule_replacement_invalidates_stale_draft_without_overwriting_version(client):
    """Only one version of a logical rule may be approved, and old drafts cannot stay actionable."""
    p, _, _, old, _ = setup_workflow(client)
    data(scan_legacy(client, p))
    notice = first_notice(client)
    new = data(
        client.post(
            "/api/v1/reminder-rules",
            json={
                k: v
                for k, v in {**old, "version_label": "V2", "days_before": 5}.items()
                if k
                in (
                    "rule_code",
                    "version_label",
                    "node_type_code",
                    "source_ref",
                    "days_before",
                    "day_basis",
                    "calendar_id",
                    "recipient_role_code",
                    "catch_up_days",
                )
            },
        ),
        201,
    )
    approval(client, "reminder-rules", new)
    rules = data(client.get("/api/v1/reminder-rules"))
    assert {r["version_label"]: r["status"] for r in rules} == {"V1": "retired", "V2": "approved"}
    assert data(client.get(f"/api/v1/notifications/{notice['id']}"))["status"] == "invalidated"
    assert data(scan(client, p, "2026-10-21"))["generated"] == 1


def test_cancelled_node_stops_reminders_and_preserves_sent_notice(client):
    """TC016: sent history remains intact while a cancelled node cannot generate new work."""
    p, node, _, _, _ = setup_workflow(client)
    data(scan(client, p))
    notice = sent = first_notice(client)
    assert sent["status"] == "sent" and sent["reviews"] == []
    node = data(client.get(f"/api/v1/milestones/{node['id']}"))
    data(
        client.post(
            f"/api/v1/milestones/{node['id']}/cancel",
            headers={"If-Match": str(node["row_version"])},
            json={"reason": "业务确认取消，用于测试"},
        )
    )
    assert data(scan(client, p))["items"][0]["skipped_reason"] == "MILESTONE_CANCELLED"
    historic = data(client.get(f"/api/v1/notifications/{notice['id']}"))
    assert (
        historic["status"] == "sent"
        and historic["body"] == sent["body"]
        and len(historic["deliveries"]) == 1
    )
    assert data(client.get("/api/v1/tasks"))["items"][0]["status"] == "cancelled"


def test_sample_templates_stay_unapproved_and_match_workbook(factory):
    """Source Excel says pending business confirmation, so seed cannot invent approvals or work calendars."""
    from pathlib import Path

    from app.phase2_seed import load_action_drafts
    from app.seed import load_sample
    from app.workflow_models import ActionItem, ActionTemplate, WorkCalendar

    path = Path(__file__).resolve().parents[2] / "模拟业务测试数据 V0.1.xlsx"
    with factory.begin() as db:
        load_sample(db, path)
        assert load_action_drafts(db, path, ADMIN_ID) == 11
        assert load_action_drafts(db, path, ADMIN_ID) == 0
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ActionItem)) == 24
        assert all(
            t.status == "draft" and t.approved_by is None
            for t in db.scalars(select(ActionTemplate))
        )
        assert db.scalar(select(func.count()).select_from(WorkCalendar)) == 0
        for code, expected in [
            ("H028-N011", "2026-10-19"),
            ("H028-N013", "2026-10-21"),
            ("H031-N014", "2026-10-18"),
        ]:
            from app.models import Milestone, PlanItem
            from app.workflow import trigger_date

            node = db.scalar(select(Milestone).where(Milestone.milestone_code == code))
            item = db.scalar(select(PlanItem).where(PlanItem.milestone_id == node.id))
            day, reason = trigger_date(db, item.planned_date, 7, "calendar_day", None)
            assert reason is None and day.isoformat() == expected


def test_explicit_catchup_window_allows_one_late_scan_without_implicit_backfill(client):
    """TC009 needs a configured catchup window; missing a day must not imply unlimited historical work."""
    p, _, _, _, _ = setup_workflow(client, catch_up=1)
    # Activation may already scan the actual business day. The preview must still enforce the window.
    result = data(scan(client, p, "2026-10-20", False))
    assert result["items"][0].get("trigger_date") == "2026-10-19"
    assert result["items"][0]["skipped_reason"] in (None, "ALREADY_GENERATED")
    assert (
        data(scan(client, p, "2026-10-21", False))["items"][0]["skipped_reason"]
        == "OUTSIDE_TRIGGER_WINDOW"
    )


def test_concurrent_scans_never_duplicate_tasks_or_notifications(client, factory):
    """Two schedulers or a retried HTTP request must produce one business reminder and one task."""
    from concurrent.futures import ThreadPoolExecutor

    p, _, _, _, _ = setup_workflow(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: scan(client, p), range(2)))
    statuses = [r.status_code for r in responses]
    assert 200 in statuses and all(s in (200, 409) for s in statuses)
    if factory.kw["bind"].dialect.name == "postgresql":
        assert statuses == [200, 200]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Reminder)) == 1
        assert db.scalar(select(func.count()).select_from(Task)) == 1
        assert db.scalar(select(func.count()).select_from(Notification)) == 1
        assert db.scalar(select(func.count()).select_from(InboxMessage)) == 1
        assert db.scalar(select(func.count()).select_from(DeliveryAttempt)) == 1


def test_worker_automatically_delivers_reminders_without_per_notice_approval(
    client, factory, monkeypatch
):
    """Approved rules deliver directly to recipients without human login or duplicate delivery."""
    from datetime import datetime, timezone

    from app import worker

    p, _, _, _, _ = setup_workflow(client)
    monkeypatch.setattr(worker, "now", lambda: datetime(2026, 10, 19, tzinfo=timezone.utc))
    assert worker.run_once(factory) == 1
    assert worker.run_once(factory) == 0
    notice = first_notice(client)
    assert notice["status"] == "sent" and notice["reviews"] == []
    assert len(notice["deliveries"]) == 1
    assert notice["deliveries"][0]["attempt_state"] == "delivered"
    inbox = data(client.get("/api/v1/inbox"))
    assert len(inbox) == 1 and inbox[0]["notification_id"] == notice["id"]
    url = f"/api/v1/notifications/{notice['id']}"
    for suffix, payload in (
        ("/draft", {"title": "改写", "body": "发送后不可改"}),
        ("/ai-draft", {}),
        ("/submit-review", None),
        ("/dispatch", {"channel": "email"}),
    ):
        response = client.request(
            "PATCH" if suffix == "/draft" else "POST",
            url + suffix,
            headers={"If-Match": str(notice["row_version"])},
            json=payload,
        )
        assert response.status_code == 409
    data(
        client.post(
            url + "/dispatch",
            headers={"If-Match": str(notice["row_version"])},
            json={"channel": "in_app"},
        )
    )
    with as_reviewer(client):
        assert data(client.get("/api/v1/inbox")) == []
        assert client.post(f"/api/v1/inbox/{inbox[0]['id']}/read").status_code == 404
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(InboxMessage)) == 1
        assert db.scalar(select(func.count()).select_from(DeliveryAttempt)) == 1


def test_failed_automatic_delivery_rolls_back_generation_and_can_retry(
    client, factory, monkeypatch
):
    from datetime import datetime, timezone

    from app import worker

    setup_workflow(client)
    monkeypatch.setattr(worker, "now", lambda: datetime(2026, 10, 19, tzinfo=timezone.utc))
    from app.delivery import deliver

    def fail_after_delivery(*args):
        deliver(*args)
        raise RuntimeError("delivery failed")

    with patch("app.workflow.deliver", side_effect=fail_after_delivery):
        with pytest.raises(RuntimeError, match="delivery failed"):
            worker.run_once(factory)
    with factory() as db:
        for model in (Reminder, Notification, Task, InboxMessage, DeliveryAttempt):
            assert db.scalar(select(func.count()).select_from(model)) == 0
    assert worker.run_once(factory) == 1
    assert len(data(client.get("/api/v1/inbox"))) == 1


@pytest.mark.parametrize("blocked", ["rule", "plan", "account", "membership"])
def test_worker_cannot_deliver_without_approved_sources_and_active_recipient(
    client, factory, monkeypatch, blocked
):
    from datetime import datetime, timezone

    from app import worker
    from app.models import Credential, PlanVersion, ProjectMember
    from app.workflow_models import ReminderRule

    p, _, _, rule, _ = setup_workflow(client)
    with factory.begin() as db:
        if blocked == "rule":
            db.get(ReminderRule, rule["id"]).status = "draft"
        elif blocked == "plan":
            plan = db.scalar(select(PlanVersion).where(PlanVersion.project_id == p["id"]))
            plan.status = "draft"
        elif blocked == "account":
            db.scalar(select(Credential).where(Credential.user_id == ADMIN_ID)).enabled = False
        else:
            db.scalar(
                select(ProjectMember).where(
                    ProjectMember.project_id == p["id"],
                    ProjectMember.user_id == ADMIN_ID,
                    ProjectMember.role_code == "admin",
                )
            ).active = False
    monkeypatch.setattr(worker, "now", lambda: datetime(2026, 10, 19, tzinfo=timezone.utc))
    assert worker.run_once(factory) == 0
    with factory() as db:
        for model in (Reminder, Notification, Task, InboxMessage, DeliveryAttempt):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def test_plan_activation_also_delivers_due_reminders(client, monkeypatch):
    from datetime import datetime, timezone

    from app import services

    monkeypatch.setattr(services, "now", lambda: datetime(2026, 10, 19, tzinfo=timezone.utc))
    p, *_ = setup_workflow(client)
    assert first_notice(client)["status"] == "sent"
    assert len(data(client.get("/api/v1/inbox"))) == 1
    assert data(scan(client, p))["generated"] == 0


def test_rule_replacement_recreates_cancelled_tasks_for_new_rule_but_not_each_recipient(client):
    """A new approved rule must not reuse its cancelled old task, nor duplicate tasks for recipients."""
    p, _, _, old, _ = setup_workflow(client)
    data(
        client.put(
            f"/api/v1/projects/{p['id']}/members",
            json={"user_id": REVIEWER_ID, "role_code": "admin"},
        )
    )
    assert data(scan(client, p))["generated"] == 2
    assert data(client.get("/api/v1/tasks"))["total"] == 1
    new = data(
        client.post(
            "/api/v1/reminder-rules",
            json={
                "rule_code": old["rule_code"],
                "version_label": "V2",
                "node_type_code": "设计资料",
                "source_ref": "新版规则",
                "days_before": 5,
                "day_basis": "calendar_day",
                "recipient_role_code": "admin",
                "catch_up_days": 0,
            },
        ),
        201,
    )
    approval(client, "reminder-rules", new)
    assert data(scan(client, p, "2026-10-21"))["generated"] == 2
    tasks = data(client.get("/api/v1/tasks"))["items"]
    assert len(tasks) == 2 and {t["status"] for t in tasks} == {"cancelled", "unassigned"}
    assert len({t["rule_version_id"] for t in tasks}) == 2
    assert data(client.get("/api/v1/notifications"))["total"] == 4


def test_readonly_role_cannot_be_made_executor_without_edit_permission(client):
    """Assignment must preserve the established viewer-is-readonly boundary."""
    p, _, _, _, _ = setup_workflow(client)
    data(scan(client, p))
    data(
        client.put(
            f"/api/v1/projects/{p['id']}/members",
            json={"user_id": VIEWER_ID, "role_code": "viewer"},
        )
    )
    task = data(client.get("/api/v1/tasks"))["items"][0]
    assert (
        client.patch(
            f"/api/v1/tasks/{task['id']}",
            headers={"If-Match": str(task["row_version"])},
            json={"assignee_id": VIEWER_ID, "reason": "尝试将只读人员当作执行人"},
        ).status_code
        == 422
    )


def test_reviewer_can_return_rule_when_calendar_is_not_approved(client):
    """Missing calendar approval must prevent activation, not trap invalid configuration in review."""
    create(client)
    calendar = data(
        client.post(
            "/api/v1/work-calendars",
            json={
                "calendar_code": "UNAPPROVED",
                "version_label": "V1",
                "source_ref": "待确认日历",
                "start_date": "2026-10-19",
                "end_date": "2026-10-19",
                "days": [{"calendar_date": "2026-10-19", "is_workday": True}],
            },
        ),
        201,
    )
    rule = data(
        client.post(
            "/api/v1/reminder-rules",
            json={
                "rule_code": "WORK-PENDING",
                "version_label": "V1",
                "node_type_code": "设计资料",
                "source_ref": "待确认工作日规则",
                "days_before": 1,
                "day_basis": "workday",
                "calendar_id": calendar["id"],
                "recipient_role_code": "editor",
            },
        ),
        201,
    )
    rule = data(
        client.post(
            f"/api/v1/reminder-rules/{rule['id']}/submit-review",
            headers={"If-Match": str(rule["row_version"])},
        )
    )
    with as_reviewer(client):
        path = f"/api/v1/reminder-rules/{rule['id']}/review"
        assert (
            client.post(
                path,
                headers={"If-Match": str(rule["row_version"])},
                json={"decision": "approved", "approval_ref": "不能越过日历审批"},
            ).status_code
            == 409
        )
        returned = data(
            client.post(
                path,
                headers={"If-Match": str(rule["row_version"])},
                json={"decision": "returned", "approval_ref": "请先完成企业日历批准"},
            )
        )
        assert returned["status"] == "draft"


def test_config_submitter_joins_compilers_without_erasing_original_creator(client, factory):
    """A second operator cannot submit somebody else's draft and then approve that same submission."""
    from app.models import Credential

    p, _ = create(client)
    template = data(client.post("/api/v1/action-templates", json=template_payload()), 201)
    with factory.begin() as db:
        db.scalar(
            select(Credential).where(Credential.username == "reviewer")
        ).is_system_admin = True
    with as_reviewer(client):
        template = data(
            client.post(
                f"/api/v1/action-templates/{template['id']}/submit-review",
                headers={"If-Match": str(template["row_version"])},
            )
        )
        assert template["created_by"] == ADMIN_ID
        assert set(template["editor_ids"]) == {ADMIN_ID, REVIEWER_ID}
        assert (
            client.post(
                f"/api/v1/action-templates/{template['id']}/review",
                headers={"If-Match": str(template["row_version"])},
                json={"decision": "approved", "approval_ref": "提交人不得自审"},
            ).status_code
            == 403
        )
    assert (
        client.post(
            f"/api/v1/action-templates/{template['id']}/review",
            headers={"If-Match": str(template["row_version"])},
            json={"decision": "approved", "approval_ref": "原编制人也不得自审"},
        ).status_code
        == 403
    )
    data(
        client.put(
            f"/api/v1/projects/{p['id']}/members",
            json={"user_id": VIEWER_ID, "role_code": "reviewer"},
        )
    )
    login_as(client, "viewer")
    approved = data(
        client.post(
            f"/api/v1/action-templates/{template['id']}/review",
            headers={"If-Match": str(template["row_version"])},
            json={"decision": "approved", "approval_ref": "第三人独立审核"},
        )
    )
    assert approved["status"] == "approved" and approved["created_by"] == ADMIN_ID


def test_explicit_catchup_window_is_honored_without_unconfirmed_deadline_clipping(client):
    """An approved catchup window is the authority; code must not invent a second cutoff at the plan date."""
    p, _, _, _, _ = setup_workflow(client, catch_up=20)
    preview = data(scan(client, p, "2026-11-01", False))
    assert preview["items"][0]["trigger_date"] == "2026-10-19"
    assert preview["items"][0]["skipped_reason"] in (None, "ALREADY_GENERATED")
    assert (
        data(scan(client, p, "2026-11-09", False))["items"][0]["skipped_reason"]
        == "OUTSIDE_TRIGGER_WINDOW"
    )
