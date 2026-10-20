"""One connected simulated business chain; real MaaS execution is explicit and opt-in."""

import copy
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from test_evaluation import ADMIN, grant, sample
from test_workflow import data, first_notice, scan, setup_workflow, submit_notice

from app import ai_service
from app.config import settings
from app.db import SessionLocal
from app.llm_models import SERVICE_ID, LLMConfig, LLMModel, LLMSelection
from app.metrics import digest
from app.models import ActualRecord
from conftest import REVIEWER_ID, as_reviewer, login_as

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def model_acceptance(client, factory, monkeypatch):
    evidence = {"kind": "mock", "calls": [], "completed_steps": [], "status": "failed"}
    if os.getenv("RUN_REAL_LLM_ACCEPTANCE") != "1":
        monkeypatch.setattr(settings, "ai_provider", "mock")
        monkeypatch.setattr(
            ai_service, "client_factory", lambda **_: pytest.fail("Mock验收不应请求外部模型")
        )
        yield evidence
        return

    # Only the saved model configuration is read from the local DB. Never copy business tables.
    with SessionLocal() as source:
        cfg = source.get(LLMConfig, SERVICE_ID)
        if not cfg or cfg.mode != "maas" or not cfg.enabled or not cfg.encrypted_api_key:
            pytest.fail("真实验收要求管理员已明确启用MaaS并保存Key；不自动启用或回退环境Key")
        config_values = {
            key: copy.deepcopy(getattr(cfg, key))
            for key in (
                "id",
                "service_name",
                "base_url",
                "adapter",
                "mode",
                "enabled",
                "timeout_seconds",
                "encrypted_api_key",
                "credential_updated_at",
                "revision",
                "endpoint_revision",
                "updated_by",
            )
        }
        choices = {s.scenario: s.model_config_id for s in source.scalars(select(LLMSelection))}
        models = list(
            source.scalars(
                select(LLMModel).where(
                    LLMModel.service_id == cfg.id,
                    LLMModel.endpoint_revision == cfg.endpoint_revision,
                    LLMModel.enabled.is_(True),
                    LLMModel.verification_status == "available",
                    LLMModel.tested_revision == cfg.revision,
                )
            )
        )
        if choices.get("default") not in {m.id for m in models}:
            pytest.fail("真实验收须先由管理员测试并选择默认模型")
        model_values = [
            {
                key: copy.deepcopy(getattr(m, key))
                for key in (
                    "id",
                    "service_id",
                    "endpoint_revision",
                    "model_id",
                    "display_name",
                    "source",
                    "enabled",
                    "verification_status",
                    "tested_revision",
                    "last_tested_at",
                )
            }
            for m in models
        ]
        original_digest = digest(jsonable_encoder([config_values, choices]))

    with factory.begin() as db:
        db.add(LLMConfig(**config_values))
        db.flush()
        for values in model_values:
            db.add(LLMModel(**values))
        db.flush()
        for scenario, model_id in choices.items():
            db.add(LLMSelection(service_id=SERVICE_ID, scenario=scenario, model_config_id=model_id))

    # Exercise a distinct notification scenario in the disposable DB when a tested model exists.
    requested = os.getenv("REAL_NOTIFICATION_MODEL")
    alternative = next((m for m in model_values if m["model_id"] == requested), None)
    if requested and not alternative:
        pytest.fail("指定场景模型尚未通过当前凭据的基础验证")
    if alternative:
        current = data(client.get("/api/v1/settings/llm"))
        data(
            client.put(
                "/api/v1/settings/llm/scenario-models",
                headers={"If-Match": str(current["row_version"])},
                json={"analysis": choices.get("analysis"), "notification": alternative["id"]},
            )
        )

    timeout = int(os.getenv("REAL_LLM_TIMEOUT_SECONDS", str(config_values["timeout_seconds"])))
    assert 1 <= timeout <= 60
    if timeout != config_values["timeout_seconds"]:
        current = data(client.get("/api/v1/settings/llm"))
        body = {k: current[k] for k in ("service_name", "base_url", "adapter", "mode", "enabled")}
        data(
            client.put(
                "/api/v1/settings/llm",
                headers={"If-Match": str(current["row_version"])},
                json={**body, "timeout_seconds": timeout},
            )
        )
    evidence.update(
        source_timeout_seconds=config_values["timeout_seconds"], acceptance_timeout_seconds=timeout
    )

    class GuardedClient(httpx.Client):
        @contextmanager
        def stream(self, method, url, **kwargs):
            body = kwargs["json"]
            assert body["response_format"]["type"] == "json_schema"
            schema = body["response_format"]["json_schema"]
            assert schema["strict"] is True and schema["schema"]["additionalProperties"] is False
            descriptors = json.loads(body["messages"][1]["content"])
            assert all(set(f) == {"id", "section", "kind"} for f in descriptors)
            assert len(evidence["calls"]) < 4, "不自动重试或进行未计划的外部调用"
            call = {
                "model_id": body["model"],
                "strict_schema": True,
                "fact_count": len(descriptors),
                "outbound_fields": ["id", "section", "kind"],
            }
            evidence["calls"].append(call)
            started = time.monotonic()
            try:
                with super().stream(method, url, **kwargs) as response:
                    call["http_status"] = response.status_code
                    yield response
            except httpx.TimeoutException:
                call["transport_outcome"] = "timeout"
                raise
            finally:
                call["elapsed_seconds"] = round(time.monotonic() - started, 2)

    def guarded_factory(**kwargs):
        assert kwargs["verify"] is True and kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return GuardedClient(**kwargs)

    monkeypatch.setattr(ai_service, "client_factory", guarded_factory)
    evidence.update(
        kind="real_cmhk",
        default_model=next(m["model_id"] for m in model_values if m["id"] == choices["default"]),
        notification_model=(
            alternative["model_id"]
            if alternative
            else next(
                m["model_id"]
                for m in model_values
                if m["id"] == choices.get("notification", choices["default"])
            )
        ),
        notification_follows_default=not alternative and not choices.get("notification"),
        scenario_override_used=bool(alternative),
    )
    try:
        yield evidence
    finally:
        with SessionLocal() as source:
            cfg = source.get(LLMConfig, SERVICE_ID)
            after = {key: copy.deepcopy(getattr(cfg, key)) for key in config_values}
            choices_after = {
                s.scenario: s.model_config_id for s in source.scalars(select(LLMSelection))
            }
            unchanged = digest(jsonable_encoder([after, choices_after])) == original_digest
        evidence["source_configuration_unchanged"] = unchanged
        evidence["verified_at"] = datetime.now(timezone.utc).isoformat()
        evidence_name = (
            "real-model-scenario-verification.json" if requested else "real-model-verification.json"
        )
        (ROOT / "docs" / evidence_name).write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
        )
        assert unchanged, "验收不能改写本机管理员配置"


def test_complete_simulated_business_chain(client, factory, model_acceptance):
    """Preparation, actual facts, money and approved AI reports must stay separately auditable."""
    evidence = model_acceptance
    real = evidence["kind"] == "real_cmhk"
    expected = "llm_assisted" if real else "mock"
    sample(factory)
    assert (
        data(client.get("/api/v1/metrics/summary?as_of=2026-10-19"))["counts"]["on_time_rate_pct"]
        == "88.2"
    )
    p, node, *_ = setup_workflow(client)
    pid = p["id"]
    evidence["completed_steps"].append("sample_excel_and_project_plan_action_rule_approval")
    assert data(scan(client, p))["generated"] == 1
    assert data(scan(client, p))["generated"] == 0
    notice = first_notice(client)
    notice_path = f"/api/v1/notifications/{notice['id']}"
    args = {"headers": {"If-Match": str(notice["row_version"])}, "json": {"allow_external": real}}
    if real:
        denied = client.post(notice_path + "/ai-draft", headers=args["headers"], json={})
        assert denied.status_code == 409 and not evidence["calls"]
    arranged = data(client.post(notice_path + "/ai-draft", **args))
    assert arranged["generation"]["generator_type"] == expected
    assert arranged["notice"]["fact_snapshot_json"] == notice["fact_snapshot_json"]
    notice = submit_notice(client, arranged["notice"])
    review = {
        "draft_version": notice["draft_version"],
        "decision": "approved",
        "comment": "仅模拟验收",
    }
    assert (
        client.post(
            notice_path + "/review", headers={"If-Match": str(notice["row_version"])}, json=review
        ).status_code
        == 403
    )
    with as_reviewer(client):
        notice = data(
            client.post(
                notice_path + "/review",
                headers={"If-Match": str(notice["row_version"])},
                json=review,
            )
        )
    assert notice["status"] == "approved_pending_send" and notice["deliveries"] == []
    for _ in range(2):
        sent = data(
            client.post(
                notice_path + "/dispatch",
                headers={"If-Match": str(notice["row_version"])},
                json={"channel": "in_app"},
            )
        )
        assert sent["status"] == "sent" and len(sent["deliveries"]) == 1
    evidence["completed_steps"].append(
        "real_notice_draft_independent_review_and_in_app_dispatch"
        if real
        else "mock_notice_review_and_dispatch"
    )

    task = data(client.get(f"/api/v1/tasks?project_id={pid}"))["items"][0]
    task_path = f"/api/v1/tasks/{task['id']}"
    task = data(
        client.patch(
            task_path,
            headers={"If-Match": str(task["row_version"])},
            json={"assignee_id": ADMIN, "reason": "模拟执行分派"},
        )
    )
    feedback = data(
        client.post(
            task_path + "/feedback",
            headers={"If-Match": str(task["row_version"])},
            json={
                "comment": "模拟材料已整理",
                "claimed_completion": True,
                "evidence_ref": "模拟资料清单",
            },
        ),
        201,
    )
    verify_path = f"/api/v1/task-feedback/{feedback['id']}/verify"
    assert (
        client.post(verify_path, json={"decision": "accepted", "comment": "自核实"}).status_code
        == 403
    )
    with as_reviewer(client):
        assert (
            data(
                client.post(
                    verify_path, json={"decision": "accepted", "comment": "独立核实模拟材料"}
                )
            )["status"]
            == "verified_done"
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
    actual = data(
        client.post(
            f"/api/v1/milestones/{node['id']}/actuals",
            json={
                "actual_date": "2026-10-26",
                "completion_flag": True,
                "evidence_ref": "独立于准备任务的模拟完成事实",
            },
        ),
        201,
    )
    with as_reviewer(client):
        data(
            client.post(
                f"/api/v1/milestone-actuals/{actual['id']}/verify",
                json={"decision": "verified", "comment": "独立确认模拟完成日期"},
            )
        )
    evidence["completed_steps"].append(
        "assigned_task_feedback_verification_and_separate_actual_fact"
    )

    grant(client, pid, can_write=True)
    grant(client, pid, REVIEWER_ID, can_verify=True)
    plan = data(
        client.post(
            f"/api/v1/projects/{pid}/financial-plans",
            json={
                "record_code": "SIM-FIN-PLAN",
                "direction": "receivable",
                "planned_date": "2026-10-26",
                "planned_amount": "123.45",
                "currency": "CNY",
                "date_source_kind": "internal_plan",
                "source_ref": "仅模拟验收计划",
            },
        ),
        201,
    )
    paid = data(
        client.post(
            f"/api/v1/projects/{pid}/financial-actuals",
            json={
                "record_code": "SIM-FIN-ACTUAL",
                "financial_plan_id": plan["id"],
                "direction": "receipt",
                "actual_date": "2026-10-26",
                "actual_amount": "123.45",
                "currency": "CNY",
                "evidence_ref": "仅模拟验收凭证",
            },
        ),
        201,
    )
    with as_reviewer(client):
        data(
            client.post(
                f"/api/v1/financial-actuals/{paid['id']}/verify",
                headers={"If-Match": str(paid["row_version"])},
                json={"decision": "verified", "comment": "模拟独立财务核实"},
            )
        )
    snap = data(
        client.post(f"/api/v1/projects/{pid}/metric-snapshots", json={"as_of": "2026-10-26"}), 201
    )
    assert snap["payload_json"]["counts"]["on_time_rate_pct"] == "100.0"
    for kind in ("stage", "work_plan"):
        body = {
            "metric_snapshot_id": snap["id"],
            "report_type": kind,
            "include_finance": True,
            "allow_external": real,
        }
        headers = {"Idempotency-Key": "system-acceptance-" + kind}
        if real:
            calls = len(evidence["calls"])
            assert (
                client.post(
                    f"/api/v1/projects/{pid}/reports/draft",
                    headers=headers,
                    json={**body, "allow_external": False},
                ).status_code
                == 409
            )
            assert len(evidence["calls"]) == calls
        report = data(
            client.post(f"/api/v1/projects/{pid}/reports/draft", headers=headers, json=body), 201
        )
        assert (
            report["generator_type"] == expected
            and report["validation_json"]["fact_references_valid"]
        )
        assert "123.45" in report["content"] and "100.0%" in report["content"]
        if real:
            calls = len(evidence["calls"])
        assert (
            data(
                client.post(f"/api/v1/projects/{pid}/reports/draft", headers=headers, json=body),
                201,
            )["id"]
            == report["id"]
        )
        if real:
            assert len(evidence["calls"]) == calls
        url = f"/api/v1/reports/{report['id']}"
        submitted = data(
            client.post(url + "/submit-review", headers={"If-Match": str(report["row_version"])})
        )
        review = {"decision": "approved", "comment": "独立核对模拟事实引用"}
        assert (
            client.post(
                url + "/review", headers={"If-Match": str(submitted["row_version"])}, json=review
            ).status_code
            == 403
        )
        with as_reviewer(client):
            approved = data(
                client.post(
                    url + "/review",
                    headers={"If-Match": str(submitted["row_version"])},
                    json=review,
                )
            )
            assert (
                approved["reviews"][0]["content_digest"]
                == report["validation_json"]["content_digest"]
            )
        exported = client.get(url + "/export")
        assert exported.status_code == 200 and "approved" in exported.text
        assert exported.headers["content-security-policy"] == "default-src 'none'; sandbox"
    evidence["completed_steps"].append(
        "verified_finance_snapshot_stage_and_work_plan_reports_approval_export"
    )
    sample_project = next(
        p for p in data(client.get("/api/v1/projects"))["items"] if p["project_code"] == "P-H028"
    )
    sample_snap = data(
        client.post(
            f"/api/v1/projects/{sample_project['id']}/metric-snapshots",
            json={"as_of": "2026-10-19"},
        ),
        201,
    )
    sample_report = data(
        client.post(
            f"/api/v1/projects/{sample_project['id']}/reports/draft",
            headers={"Idempotency-Key": "existing-excel-sample-report"},
            json={"metric_snapshot_id": sample_snap["id"], "allow_external": real},
        ),
        201,
    )
    assert sample_report["generator_type"] == expected
    assert (
        "93.3%" in sample_report["content"]
        and sample_report["validation_json"]["fact_references_valid"]
    )
    evidence["completed_steps"].append(
        "existing_P_H028_excel_project_real_stage_report"
        if real
        else "existing_P_H028_excel_project_mock_report"
    )
    login_as(client, "viewer")
    assert client.get(url).status_code == 404
    if real:
        assert len(evidence["calls"]) == 4
        assert evidence["calls"][0]["model_id"] == evidence["calls"][2]["model_id"]
        assert evidence["calls"][1]["model_id"] == evidence["default_model"]
        if evidence["notification_model"]:
            assert evidence["calls"][0]["model_id"] == evidence["notification_model"]
    evidence["status"] = "passed"
