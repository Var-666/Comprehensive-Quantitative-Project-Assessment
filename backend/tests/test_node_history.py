from sqlalchemy import select
from test_phase1 import create, node_payload
from test_plan_deltas import activate, edit, new_plan

from app.models import AuditEvent
from conftest import as_reviewer


def test_node_history_labels_versions_and_operators_without_changing_audit_facts(client, factory):
    project, first = create(client)
    node = client.post(
        f"/api/v1/projects/{project['id']}/milestones", json=node_payload(first["id"])
    ).json()["data"]
    activate(client, project, first)
    second = new_plan(client, project)
    edit(client, node, second, planned_date="2026-10-03", change_reason="雨天后延两天")
    actual = client.post(
        f"/api/v1/milestones/{node['id']}/actuals",
        json={"actual_date": "2026-10-03", "completion_flag": True, "evidence_ref": "验收单"},
    ).json()["data"]
    with as_reviewer(client):
        response = client.post(
            f"/api/v1/milestone-actuals/{actual['id']}/verify",
            json={"decision": "verified", "comment": "核实通过"},
        )
        assert response.status_code == 200, response.text
    response = client.get(f"/api/v1/milestones/{node['id']}?plan_version_id={second['id']}")
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert [(h["version_label"], h["version_status"]) for h in result["history"]] == [
        (second["version_label"], "draft"),
        (first["version_label"], "effective"),
    ]
    assert [h["planned_date"] for h in result["history"]] == ["2026-10-03", "2026-10-01"]
    assert result["history"][1]["plan_version_id"] == first["id"]
    events = {e["action"]: e for e in result["audit_events"]}
    assert events["create"]["actor_name"] == "张工"
    assert events["verify"]["actor_name"] == "审核人员"
    assert events["edit_draft"]["before_json"]["planned_date"] == "2026-10-01"
    assert events["edit_draft"]["after_json"]["planned_date"] == "2026-10-03"
    assert events["verify"]["after_json"]["comment"] == "核实通过"
    with factory() as db:
        stored = db.scalar(select(AuditEvent).where(AuditEvent.id == events["edit_draft"]["id"]))
        assert "actor_name" not in stored.after_json
        assert stored.after_json["plan_version_id"] == second["id"]


def test_node_history_keeps_system_and_missing_historical_operators(client, factory):
    project, plan = create(client)
    node = client.post(
        f"/api/v1/projects/{project['id']}/milestones", json=node_payload(plan["id"])
    ).json()["data"]
    with factory.begin() as db:
        for actor in ["system", "legacy-operator"]:
            db.add(
                AuditEvent(
                    aggregate_type="milestones",
                    aggregate_id=node["id"],
                    action="historical_event",
                    actor_id=actor,
                    before_json=None,
                    after_json=None,
                    request_id="history-test",
                )
            )
    events = client.get(f"/api/v1/milestones/{node['id']}").json()["data"]["audit_events"]
    names = {e["actor_id"]: e["actor_name"] for e in events}
    assert names["system"] == "系统"
    assert names["legacy-operator"] == "历史操作人未记录"
    assert len(events) == 3
