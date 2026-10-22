"""Business intent: missing facts never become delay, money or verified completion."""

from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import select

from app import ai_service, llm_provider
from app.config import settings
from app.evaluation_models import FinancialActual, MetricSnapshot, ReportDraft, ReportReview
from app.models import ActualRecord, AuditEvent, Milestone, PlanVersion, Project, ProjectMember
from app.phase3_seed import load_finance
from app.seed import load_sample
from conftest import REVIEWER_ID, VIEWER_ID, as_reviewer, login_as
from test_phase1 import create, node_payload

ADMIN = "00000000-0000-0000-0000-000000000002"
FILE = Path(__file__).resolve().parents[2] / "模拟业务测试数据 V0.1.xlsx"


def sample(factory):
    with factory.begin() as db:
        load_sample(db, FILE)
        for p in db.scalars(select(Project)):
            db.add(ProjectMember(project_id=p.id, user_id=ADMIN, role_code="admin"))
            db.add(ProjectMember(project_id=p.id, user_id=REVIEWER_ID, role_code="reviewer"))


def snapshot(client, p):
    r = client.post(f"/api/v1/projects/{p}/metric-snapshots", json={"as_of": "2026-10-19"})
    assert r.status_code == 201, r.text
    return r.json()["data"]


def grant(client, p, user=ADMIN, **extra):
    r = client.put(
        f"/api/v1/projects/{p}/financial-access", json={"user_id": user, "can_read": True, **extra}
    )
    assert r.status_code == 200, r.text


def test_excel_trial_formula_and_aggregate_are_reproducible(client, factory):
    sample(factory)
    result = client.get("/api/v1/metrics/summary?as_of=2026-10-19").json()["data"]
    expected = {
        "P-H028": (16, 14, 1, 1, "93.3"),
        "P-H031": (12, 10, 2, 0, "83.3"),
        "P-H014": (8, 6, 1, 1, "85.7"),
    }
    for p in result["projects"]:
        c = p["counts"]
        assert (
            tuple(
                c[k]
                for k in [
                    "due_total",
                    "on_time_completed",
                    "late_completed",
                    "pending_verification",
                    "on_time_rate_pct",
                ]
            )
            == expected[p["project_code"]]
        )
        assert c["composite_score"] is None
    assert result["counts"]["on_time_rate_pct"] == "88.2"
    assert result["counts"]["due_total"] == 36
    assert (
        client.get(
            "/api/v1/metrics/summary?as_of=2026-10-19&formula_version=unconfirmed"
        ).status_code
        == 422
    )
    h = next(p for p in result["projects"] if p["project_code"] == "P-H028")
    row = next(e for e in h["evidence"] if e["milestone_code"] == "H028-N006")
    assert row["deviation_days"] == 3
    assert (
        next(e for e in h["evidence"] if e["milestone_code"] == "H028-N008")["category"]
        == "pending_verification"
    )
    assert (
        next(e for e in h["evidence"] if e["milestone_code"] == "H028-N011")["category"]
        == "not_due"
    )


def test_frozen_evidence_survives_later_fact_changes(client, factory):
    sample(factory)
    p = client.get("/api/v1/projects").json()["data"]["items"][0]["id"]
    snap = snapshot(client, p)
    assert snapshot(client, p)["id"] == snap["id"]
    with factory.begin() as db:
        node = db.scalar(select(Milestone).where(Milestone.project_id == p))
        node.lifecycle_status = "cancelled"
    fresh = snapshot(client, p)
    assert fresh["id"] != snap["id"]
    assert (
        client.get(f"/api/v1/metric-snapshots/{snap['id']}").json()["data"]["payload_json"]
        == snap["payload_json"]
    )
    other = next(
        x["id"] for x in client.get("/api/v1/projects").json()["data"]["items"] if x["id"] != p
    )
    assert (
        client.get(
            f"/api/v1/projects/{other}/metric-evidence?as_of=2026-10-19&snapshot_id={snap['id']}"
        ).status_code
        == 422
    )


def test_verified_unfinished_and_after_cutoff_are_not_late_completed(client, factory):
    p, plan = create(client)
    node = client.post(
        f"/api/v1/projects/{p['id']}/milestones", json=node_payload(plan["id"])
    ).json()["data"]
    with factory.begin() as db:
        v = db.get(PlanVersion, plan["id"])
        v.status = "effective"
        db.get(Project, p["id"]).current_plan_version_id = v.id
        db.add(
            ActualRecord(
                milestone_id=node["id"],
                completion_flag=False,
                verification_status="verified",
                is_current=True,
                evidence_ref="明确未完成的独立核实",
            )
        )
    r = client.get(f"/api/v1/projects/{p['id']}/metrics?as_of=2026-10-19").json()["data"]
    assert r["counts"]["confirmed_overdue_unfinished"] == 1
    assert r["counts"]["on_time_rate_pct"] is None
    with factory.begin() as db:
        a = db.scalar(select(ActualRecord))
        a.completion_flag = True
        a.actual_date = date(2026, 10, 20)
    r = client.get(f"/api/v1/projects/{p['id']}/metrics?as_of=2026-10-19").json()["data"]
    assert r["counts"]["pending_verification"] == 1
    assert r["counts"]["late_completed"] == 0


def test_draft_plan_cannot_be_evaluation_baseline(client):
    p, _ = create(client)
    assert client.get(f"/api/v1/projects/{p['id']}/metrics?as_of=2026-10-19").status_code == 409
    assert client.get("/api/v1/metrics/summary?as_of=2026-10-19").json()["data"]["unavailable"]


def test_finance_requires_extra_grant_and_never_copies_plan_to_actual(client, factory):
    sample(factory)
    with factory.begin() as db:
        assert load_finance(db, FILE, "CNY") == 6
        assert load_finance(db, FILE, "CNY") == 0
        assert len(list(db.scalars(select(FinancialActual)))) == 1
        p = db.scalar(select(Project.id).where(Project.project_code == "P-H028"))
    path = f"/api/v1/projects/{p}/financial-records?as_of=2026-10-19"
    assert client.get(path).status_code == 403
    grant(client, p, can_write=True)
    data = client.get(path).json()["data"]
    assert len(data["plans"]) == 2 and data["actuals"] == []
    assert all(g["verified_actual_total"] is None for g in data["groups"])
    assert data["actual_data_complete"] is False
    snap = snapshot(client, p)
    report = client.post(
        f"/api/v1/projects/{p}/reports/draft",
        headers={"Idempotency-Key": "finance"},
        json={"metric_snapshot_id": snap["id"], "include_finance": True},
    ).json()["data"]
    assert "8000000.00" in report["content"] and "待核实" in report["content"]
    grant(client, p, can_read=False)
    assert client.get(f"/api/v1/reports/{report['id']}").status_code == 403
    assert client.get(f"/api/v1/reports/{report['id']}/export").status_code == 403
    assert (
        client.delete(
            f"/api/v1/reports/{report['id']}", headers={"If-Match": str(report["row_version"])}
        ).status_code
        == 403
    )
    with factory() as db:
        assert db.get(ReportDraft, report["id"]).deleted_at is None
    assert client.get(f"/api/v1/projects/{p}/reports").json()["data"] == []


def test_finance_decimal_and_independent_verification(client):
    p, _ = create(client)
    pid = p["id"]
    grant(client, pid, can_write=True, can_verify=True)
    grant(client, pid, REVIEWER_ID, can_verify=True)
    body = {
        "record_code": "F-1",
        "direction": "receipt",
        "actual_date": "2026-10-01",
        "actual_amount": "100.11",
        "currency": "CNY",
        "evidence_ref": "凭证X",
    }
    r = client.post(f"/api/v1/projects/{pid}/financial-actuals", json=body)
    assert r.status_code == 201, r.text
    obj = r.json()["data"]
    assert obj["actual_amount"] == "100.11"
    path = f"/api/v1/financial-actuals/{obj['id']}/verify"
    args = {
        "headers": {"If-Match": str(obj["row_version"])},
        "json": {"decision": "verified", "comment": "独立核实凭证"},
    }
    assert client.post(path, **args).status_code == 403
    with as_reviewer(client):
        assert client.post(path, **args).status_code == 200
    assert client.post(f"/api/v1/projects/{pid}/financial-actuals", json=body).status_code == 409
    assert (
        client.post(
            f"/api/v1/projects/{pid}/financial-actuals",
            json={**body, "record_code": "F-2", "actual_amount": "1.001"},
        ).status_code
        == 422
    )
    summary = client.get(f"/api/v1/projects/{pid}/financial-records?as_of=2026-10-19").json()[
        "data"
    ]
    assert summary["groups"][0]["verified_actual_total"] == "100.11"
    assert (
        client.get(
            f"/api/v1/projects/{pid}/financial-records?as_of=2026-10-19&direction=payable"
        ).json()["data"]["actuals"]
        == []
    )
    assert (
        client.put(
            f"/api/v1/projects/{pid}/financial-access",
            json={"user_id": "not-a-uuid", "can_read": True},
        ).status_code
        == 422
    )


def test_report_idempotency_independent_approval_and_escaped_export(client, factory):
    sample(factory)
    p = client.get("/api/v1/projects").json()["data"]["items"][0]["id"]
    snap = snapshot(client, p)
    body = {"metric_snapshot_id": snap["id"]}
    args = {"headers": {"Idempotency-Key": "report-1"}, "json": body}
    report = client.post(f"/api/v1/projects/{p}/reports/draft", **args).json()["data"]
    assert report["generator_type"] == "mock" and report["review_status"] == "draft"
    assert "Mock" in report["content"] and report["fact_bundle_json"]["finance"] is None
    assert (
        client.post(f"/api/v1/projects/{p}/reports/draft", **args).json()["data"]["id"]
        == report["id"]
    )
    assert (
        client.post(
            f"/api/v1/projects/{p}/reports/draft",
            headers=args["headers"],
            json={**body, "report_type": "exceptions"},
        ).status_code
        == 409
    )
    path = f"/api/v1/reports/{report['id']}"
    submitted = client.post(
        path + "/submit-review", headers={"If-Match": str(report["row_version"])}
    ).json()["data"]
    review = {
        "headers": {"If-Match": str(submitted["row_version"])},
        "json": {"decision": "approved", "comment": "已核对冻结事实"},
    }
    assert client.post(path + "/review", **review).status_code == 403
    with as_reviewer(client):
        approved = client.post(path + "/review", **review)
        assert approved.status_code == 200, approved.text
        assert (
            approved.json()["data"]["reviews"][0]["content_digest"]
            == report["validation_json"]["content_digest"]
        )
    exported = client.get(path + "/export")
    assert exported.status_code == 200 and "approved" in exported.text
    assert client.get(path + "/export?format=pdf").status_code == 422
    assert exported.headers["content-security-policy"] == "default-src 'none'; sandbox"
    login_as(client, "viewer")
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("approved", [False, True])
def test_report_delete_hides_access_preserves_audit_and_guards_versions(client, factory, approved):
    sample(factory)
    p = client.get("/api/v1/projects").json()["data"]["items"][0]["id"]
    snap = snapshot(client, p)
    args = {
        "headers": {"Idempotency-Key": "delete-report"},
        "json": {"metric_snapshot_id": snap["id"]},
    }
    report = client.post(f"/api/v1/projects/{p}/reports/draft", **args).json()["data"]
    path = f"/api/v1/reports/{report['id']}"
    if approved:
        submitted = client.post(
            path + "/submit-review", headers={"If-Match": str(report["row_version"])}
        ).json()["data"]
        with as_reviewer(client):
            report = client.post(
                path + "/review",
                headers={"If-Match": str(submitted["row_version"])},
                json={"decision": "approved", "comment": "核对冻结事实"},
            ).json()["data"]
    with factory.begin() as db:
        db.add(ProjectMember(project_id=p, user_id=VIEWER_ID, role_code="viewer"))
    login_as(client, "viewer")
    assert client.get(path).status_code == 200
    assert client.delete(path, headers={"If-Match": str(report["row_version"])}).status_code == 403
    login_as(client)
    assert client.delete(path).status_code == 422
    assert client.delete(path, headers={"If-Match": "0"}).status_code == 409
    assert client.get(path).status_code == 200
    deleted = client.delete(path, headers={"If-Match": str(report["row_version"])})
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["data"] == {"id": report["id"]}
    assert client.get(f"/api/v1/projects/{p}/reports").json()["data"] == []
    for suffix in ("", "/export"):
        assert client.get(path + suffix).status_code == 404
    assert client.delete(path, headers={"If-Match": str(report["row_version"])}).status_code == 404
    assert (
        client.post(
            path + "/submit-review", headers={"If-Match": str(report["row_version"])}
        ).status_code
        == 404
    )
    with as_reviewer(client):
        assert (
            client.post(
                path + "/review",
                headers={"If-Match": str(report["row_version"])},
                json={"decision": "approved", "comment": "不得审核已删除报告"},
            ).status_code
            == 404
        )
    replay = client.post(f"/api/v1/projects/{p}/reports/draft", **args)
    assert replay.status_code == 409 and replay.json()["error"]["code"] == "REPORT_DELETED"
    with factory() as db:
        stored = db.get(ReportDraft, report["id"])
        assert stored.deleted_at is not None and stored.row_version == report["row_version"] + 1
        assert (
            stored.content == report["content"]
            and stored.fact_bundle_json == report["fact_bundle_json"]
        )
        assert stored.review_status == report["review_status"]
        assert db.get(MetricSnapshot, snap["id"]) is not None
        assert len(
            list(db.scalars(select(ReportReview).where(ReportReview.report_id == report["id"])))
        ) == int(approved)
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.aggregate_id == report["id"], AuditEvent.action == "delete_report"
            )
        )
        assert audit.actor_id == ADMIN and audit.request_id
        assert audit.before_json["deleted_at"] is None and audit.after_json["deleted_at"]
    # A fresh generation request creates a new report without reviving the deleted one.
    fresh = client.post(
        f"/api/v1/projects/{p}/reports/draft",
        headers={"Idempotency-Key": "fresh-report"},
        json=args["json"],
    )
    assert fresh.status_code == 201 and fresh.json()["data"]["id"] != report["id"]


def test_mock_never_uses_network_and_real_requires_explicit_authorization(monkeypatch):
    facts = [{"id": "A", "section": "overview", "kind": "rate", "text": "固定事实"}]
    monkeypatch.setattr(settings, "ai_provider", "mock")
    monkeypatch.setattr(ai_service, "client_factory", lambda **kw: pytest.fail("Mock不得联网"))
    result, meta = ai_service.arrange(facts)
    assert result.overview == ["A"] and meta["external_transmission"] is False
    monkeypatch.setattr(settings, "ai_provider", "openai_compatible")
    monkeypatch.setattr(settings, "ai_external_enabled", False)
    with pytest.raises(HTTPException) as e:
        ai_service.arrange(facts, True)
    assert e.value.status_code == 409


@pytest.mark.parametrize(
    "mode",
    [
        "valid",
        "unknown_fact",
        "omitted_fact",
        "server_error",
        "timeout",
        "free_text",
        "duplicate_suggestions",
        "forbidden_finance",
        "cross_section",
        "truncated",
    ],
)
def test_real_adapter_contract_rejects_invented_facts_without_fallback(monkeypatch, mode):
    import json

    facts = [{"id": "A", "section": "overview", "kind": "rate", "text": "敏感项目金额800万元"}]
    for name, value in [
        ("ai_provider", "openai_compatible"),
        ("ai_external_enabled", True),
        ("ai_base_url", "https://model.invalid/v1"),
        ("ai_model", "configured-model"),
        ("ai_api_key", SecretStr("test-secret")),
    ]:
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(settings, "llm_allowed_origins", "https://model.invalid")
    monkeypatch.setattr(
        llm_provider, "resolve_host", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))]
    )
    calls = []

    def handler(request):
        calls.append(request)
        assert "800" not in request.content.decode() and "敏感" not in request.content.decode()
        body = json.loads(request.content)
        codes = body["response_format"]["json_schema"]["schema"]["properties"]["suggestion_codes"][
            "items"
        ]["enum"]
        assert "verify_finance" not in codes, "未外送财务事实时Schema也不能授权财务建议"
        if mode == "timeout":
            raise httpx.ReadTimeout("network", request=request)
        if mode == "server_error":
            return httpx.Response(503, json={"secret": "provider internal detail"})
        content = {"overview": ["A"], "attention": [], "suggestion_codes": ["prepare_actions"]}
        if mode == "unknown_fact":
            content["overview"] = ["INVENTED"]
        if mode == "omitted_fact":
            content["overview"] = []
        if mode == "free_text":
            content["invented_text"] = "已全部到账"
        if mode == "duplicate_suggestions":
            content["suggestion_codes"] = ["prepare_actions", "prepare_actions"]
        if mode == "forbidden_finance":
            content["suggestion_codes"] = ["verify_finance"]
        if mode == "cross_section":
            content["overview"], content["attention"] = [], ["A"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length" if mode == "truncated" else "stop",
                        "message": {"content": json.dumps(content)},
                    }
                ]
            },
        )

    monkeypatch.setattr(
        ai_service,
        "client_factory",
        lambda **kw: httpx.Client(transport=httpx.MockTransport(handler), **kw),
    )
    if mode == "valid":
        result, meta = ai_service.arrange(facts, True)
        assert meta["generator_type"] == "llm_assisted"
        assert "敏感项目金额800万元" in ai_service.render(facts, result, "报告", meta)
    else:
        with pytest.raises(HTTPException) as e:
            ai_service.arrange(facts, True)
        assert e.value.status_code in (502, 503)
        assert "provider internal" not in str(e.value.detail)
    assert len(calls) == 1, "重试由确定性代码处理；不得让模型决定重试或静默降级"


def test_ai_notice_keeps_sources_and_requires_human_review(client):
    from test_workflow import first_notice, scan, setup_workflow, submit_notice

    p, *_ = setup_workflow(client)
    assert scan(client, p).status_code == 200
    notice = first_notice(client)
    path = f"/api/v1/notifications/{notice['id']}/ai-draft"
    r = client.post(path, headers={"If-Match": str(notice["row_version"])}, json={})
    assert r.status_code == 200, r.text
    result = r.json()["data"]
    changed = result["notice"]
    assert result["generation"]["generator_type"] == "mock"
    assert (
        changed["status"] == "draft"
        and changed["fact_snapshot_json"] == notice["fact_snapshot_json"]
    )
    assert "整理资料" in changed["body"] and "Mock" in changed["body"]
    assert changed["draft_version"] == notice["draft_version"] + 1
    assert (
        client.post(path, headers={"If-Match": str(notice["row_version"])}, json={}).status_code
        == 409
    )
    submitted = submit_notice(client, changed)
    assert (
        client.post(path, headers={"If-Match": str(submitted["row_version"])}, json={}).status_code
        == 409
    )


def test_financial_plan_link_and_project_membership_cannot_be_bypassed(client):
    p, _ = create(client)
    other, _ = create(client, "P-OTHER")
    grant(client, p["id"], can_write=True)
    grant(client, other["id"], can_write=True)
    plan = client.post(
        f"/api/v1/projects/{p['id']}/financial-plans",
        json={
            "record_code": "F-P",
            "direction": "receivable",
            "planned_date": "2026-10-01",
            "planned_amount": "999.10",
            "currency": "CNY",
            "date_source_kind": "unconfirmed",
            "source_ref": "未核实计划",
        },
    ).json()["data"]
    body = {
        "record_code": "F-A",
        "financial_plan_id": plan["id"],
        "direction": "receipt",
        "actual_date": "2026-10-01",
        "actual_amount": "10.10",
        "currency": "CNY",
        "evidence_ref": "独立凭证",
    }
    assert (
        client.post(f"/api/v1/projects/{other['id']}/financial-actuals", json=body).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/projects/{p['id']}/financial-actuals", json={**body, "currency": "USD"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/projects/{p['id']}/financial-actuals", json={**body, "direction": "payment"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/projects/{p['id']}/financial-actuals",
            json={k: v for k, v in body.items() if k != "actual_amount"},
        ).status_code
        == 422
    )
    assert (
        client.put(
            f"/api/v1/projects/{p['id']}/financial-access",
            json={"user_id": REVIEWER_ID, "can_verify": True},
        ).status_code
        == 422
    )


def test_report_export_escapes_untrusted_business_text(client, factory):
    sample(factory)
    with factory.begin() as db:
        p = db.scalar(select(Project))
        p.project_name = "<script>alert(1)</script>"
        pid = p.id
    snap = snapshot(client, pid)
    report = client.post(
        f"/api/v1/projects/{pid}/reports/draft",
        headers={"Idempotency-Key": "escape"},
        json={"metric_snapshot_id": snap["id"]},
    ).json()["data"]
    content = client.get(f"/api/v1/reports/{report['id']}/export").text
    assert "<script>" not in content and "&lt;script&gt;" in content
    assert "draft" in content and "mock" in content
