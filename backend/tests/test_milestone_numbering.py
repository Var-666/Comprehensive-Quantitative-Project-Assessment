from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from test_phase1 import create, node_payload

from app.models import Milestone
from conftest import as_reviewer


def add(client, project, plan, code=None):
    body = node_payload(plan["id"])
    if code is None:
        body.pop("milestone_code")
    else:
        body["milestone_code"] = code
    return client.post(f"/api/v1/projects/{project['id']}/milestones", json=body)


def test_auto_numbering_uses_max_suffix_and_never_reuses_cancelled_codes(client, factory):
    project, plan = create(client, "P-H001")
    assert add(client, project, plan).json()["data"]["milestone_code"] == "H001-N001"
    assert add(client, project, plan).json()["data"]["milestone_code"] == "H001-N002"
    manual = add(client, project, plan, "LEGACY-N010")
    assert manual.status_code == 201
    with factory.begin() as db:
        db.get(Milestone, manual.json()["data"]["id"]).lifecycle_status = "cancelled"
    response = add(client, project, plan)
    assert response.status_code == 201, response.text
    assert response.json()["data"]["milestone_code"] == "H001-N011"
    other, other_plan = create(client, "P-H002")
    assert add(client, other, other_plan).json()["data"]["milestone_code"] == "H002-N001"
    assert add(client, project, plan, "CUSTOM-ID").status_code == 201
    assert add(client, project, plan, "CUSTOM-ID").status_code == 409
    assert add(client, project, plan).json()["data"]["milestone_code"] == "H001-N012"


@pytest.mark.parametrize("project_code", ["P-H001", "X" * 64])
def test_numbering_expands_after_999_and_respects_code_length(client, project_code):
    project, plan = create(client, project_code)
    assert add(client, project, plan, "OLD-N999").status_code == 201
    response = add(client, project, plan)
    assert response.status_code == 201, response.text
    code = response.json()["data"]["milestone_code"]
    assert code.endswith("-N1000") and len(code) <= 64


def test_failed_create_rolls_back_auto_number_and_edit_still_requires_stable_code(client, factory):
    project, plan = create(client, "P-H003")
    with patch("app.action_matching.automatically_link", side_effect=RuntimeError("test failure")):
        with pytest.raises(RuntimeError, match="test failure"):
            add(client, project, plan)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Milestone)) == 0
    node = add(client, project, plan).json()["data"]
    assert node["milestone_code"] == "H003-N001"
    url = f"/api/v1/milestones/{node['id']}/plan-item"
    body = node_payload(plan["id"], node["milestone_code"])
    headers = {"If-Match": str(node["row_version"])}
    assert (
        client.patch(
            url, json={k: v for k, v in body.items() if k != "milestone_code"}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.patch(url, json={**body, "milestone_code": "CHANGED"}, headers=headers).status_code
        == 422
    )
    assert (
        client.patch(
            url, json={**body, "milestone_name": "改名保留编号"}, headers=headers
        ).status_code
        == 200
    )


def test_auto_numbering_retains_readonly_plan_protection(client):
    project, plan = create(client, "P-H004")
    with as_reviewer(client):
        response = client.post(
            f"/api/v1/plan-versions/{plan['id']}/activate",
            headers={"If-Match": str(plan["row_version"])},
            json={"approval_ref": "test independent approval"},
        )
        assert response.status_code == 200, response.text
    assert add(client, project, plan).status_code == 409


def test_concurrent_auto_creates_cannot_commit_duplicate_numbers(client, factory):
    project, plan = create(client, "P-H005")
    barrier = Barrier(2)

    def concurrent_create():
        barrier.wait(timeout=10)
        return add(client, project, plan)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: concurrent_create(), range(2)))
    assert all(r.status_code in (201, 409) for r in responses), [r.text for r in responses]
    assert any(r.status_code == 201 for r in responses)
    if factory.kw["bind"].dialect.name == "postgresql":
        assert all(r.status_code == 201 for r in responses)
    for response in responses:
        if response.status_code == 409:
            retry = add(client, project, plan)
            assert retry.status_code == 201, retry.text
    with factory() as db:
        codes = list(
            db.scalars(
                select(Milestone.milestone_code).where(Milestone.project_id == project["id"])
            )
        )
    assert sorted(codes) == ["H005-N001", "H005-N002"]


def test_create_without_reason_records_default_and_preserves_explicit_source(client, factory):
    project, plan = create(client, "P-REASON")
    body = node_payload(plan["id"])
    body.pop("milestone_code")
    body.pop("change_reason")
    response = client.post(f"/api/v1/projects/{project['id']}/milestones", json=body)
    assert response.status_code == 201, response.text
    node = response.json()["data"]
    assert node["plan_item"]["change_reason"] == "新增节点"
    from app.models import AuditEvent, PlanItem

    with factory() as db:
        item = db.scalar(select(PlanItem).where(PlanItem.milestone_id == node["id"]))
        assert item.change_reason == "新增节点"
        assert db.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == node["id"]))
    supplied = client.post(
        f"/api/v1/projects/{project['id']}/milestones",
        json={**body, "change_reason": "API明确提供的录入来源"},
    )
    assert supplied.status_code == 201
    assert supplied.json()["data"]["plan_item"]["change_reason"] == "API明确提供的录入来源"


def test_edit_reason_is_still_required_and_retains_real_change_history(client):
    project, plan = create(client, "P-EDIT-REASON")
    node = add(client, project, plan).json()["data"]
    body = node_payload(plan["id"], node["milestone_code"])
    body.pop("change_reason")
    url = f"/api/v1/milestones/{node['id']}/plan-item"
    headers = {"If-Match": str(node["row_version"])}
    for values in [
        body,
        {**body, "change_reason": ""},
        {**body, "change_reason": "   "},
        {**body, "change_reason": None},
    ]:
        assert client.patch(url, json=values, headers=headers).status_code == 422
    result = client.patch(
        url,
        headers=headers,
        json={**body, "planned_date": "2026-11-03", "change_reason": "根据排期调整日期"},
    )
    assert result.status_code == 200, result.text
    assert result.json()["data"]["plan_item"]["change_reason"] == "根据排期调整日期"
