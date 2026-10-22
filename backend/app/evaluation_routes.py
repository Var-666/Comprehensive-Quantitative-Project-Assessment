import csv
import io
from collections import Counter, defaultdict
from datetime import date, timedelta
from html import escape
from types import SimpleNamespace
from typing import Literal

from fastapi import Header, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select

from . import ai_service, auth, finance, metrics, reports
from . import services as svc
from . import workflow as wf
from .evaluation_models import FinancialAccess, FinancialActual, MetricSnapshot, ReportDraft
from .evaluation_schemas import (
    AssistInput,
    FinancialActualInput,
    FinancialGrant,
    FinancialPlanInput,
    ReportInput,
    ReviewInput,
    SnapshotInput,
)
from .llm_service import LLMService
from .models import Credential, Project, now
from .schemas import VerifyInput
from .workflow_models import Notification, Task
from .workflow_routes import scoped


def collection(db, principal, as_of):
    projects = list(
        db.scalars(
            select(Project)
            .where(Project.id.in_(auth.visible_projects(principal)))
            .order_by(Project.project_code)
        )
    )
    items = []
    unavailable = []
    counts = Counter()
    groups = defaultdict(Counter)
    for project in projects:
        if not project.current_plan_version_id:
            unavailable.append(
                {
                    "project_id": project.id,
                    "project_code": project.project_code,
                    "reason": "尚无生效计划",
                }
            )
            continue
        result = metrics.calculate(db, project, as_of)
        items.append(result)
        for key in metrics.CATEGORIES:
            counts[key] += result["counts"][key]
        for group in result["groups"]:
            for key in metrics.CATEGORIES:
                groups[group["node_type_code"]][key] += group[key]
    return {
        "as_of_date": as_of.isoformat(),
        "formula": metrics.FORMULA,
        "counts": metrics.totals(counts),
        "groups": [
            {"node_type_code": key, **metrics.totals(values)}
            for key, values in sorted(groups.items())
        ],
        "projects": items,
        "unavailable": unavailable,
    }


def register(app, Db, ok):
    @app.get("/api/v1/metrics/dashboard")
    def dashboard(request: Request, db: Db, as_of: date = Query(..., ge=date(2, 1, 1))):
        """Read-only dashboard; all classifications reuse trial_v1 and existing project scopes."""
        principal = request.state.principal
        current = collection(db, principal, as_of)
        projects = list(
            db.scalars(
                select(Project)
                .where(Project.id.in_(auth.visible_projects(principal)))
                .order_by(Project.project_code)
            )
        )
        months = []
        end = as_of.replace(day=1) - timedelta(days=1)
        for _ in range(6):
            start = end.replace(day=1)
            values = Counter()
            for project in projects:
                if not project.current_plan_version_id:
                    continue
                evidence = metrics.calculate(db, project, end)["evidence"]
                for row in evidence:
                    if start.isoformat() <= row["planned_date"] <= end.isoformat():
                        values[row["category"]] += 1
            months.append({"month": start.strftime("%Y-%m"), **metrics.totals(values)})
            end = start - timedelta(days=1)
        unfinished = select(Task).where(
            Task.project_id.in_(auth.visible_projects(principal)),
            Task.status.not_in(("verified_done", "cancelled")),
        )
        task_count = db.scalar(select(func.count()).select_from(unfinished.subquery()))
        upcoming = list(db.scalars(unfinished.order_by(Task.due_date, Task.id).limit(3)))
        lookup = {p["project_id"]: p for p in current["projects"]}
        rows = []
        for project in projects[:5]:
            metric = lookup.get(project.id)
            pending = (
                next(
                    (
                        r
                        for r in metric["evidence"]
                        if r["category"] not in ("excluded", "on_time_completed", "late_completed")
                    ),
                    None,
                )
                if metric
                else None
            )
            rows.append(
                {
                    **svc.project_detail(db, project),
                    "counts": metric["counts"] if metric else None,
                    "next_milestone": (
                        {k: pending[k] for k in ("milestone_name", "planned_date", "category")}
                        if pending
                        else None
                    ),
                }
            )
        return ok(
            request,
            {
                "as_of_date": as_of.isoformat(),
                "computed_at": now().isoformat(),
                "formula": metrics.FORMULA,
                "trend_basis": "最近6个完整自然月，按计划到期月份分组；以当前生效计划及当前已核实事实复算各月末，不代表当时系统知情快照。",
                "task_basis": "当前未完成执行任务按截止日排序；不是历史待办快照。",
                "months": list(reversed(months)),
                "counts": current["counts"],
                "pending_tasks": task_count,
                "upcoming_tasks": [svc.record(t) for t in upcoming],
                "projects": rows,
            },
        )

    @app.get("/api/v1/ai/config")
    def ai_config(request: Request, db: Db):
        return ok(request, LLMService.describe(db))

    @app.get("/api/v1/metrics/summary")
    def summary(
        request: Request, db: Db, as_of: date, formula_version: Literal["trial_v1"] = "trial_v1"
    ):
        return ok(request, collection(db, request.state.principal, as_of))

    @app.get("/api/v1/metrics/export")
    def export_metrics(request: Request, db: Db, as_of: date):
        data = collection(db, request.state.principal, as_of)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "项目编号",
                "项目名称",
                "截止日",
                "计划版本",
                "应完成",
                "按期完成",
                "延期完成",
                "待核对",
                "已核实逾期未完成",
                "按期率%",
                "核实覆盖率%",
                "来源摘要",
            ]
        )
        for p in data["projects"]:
            c = p["counts"]
            values = [
                p["project_code"],
                p["project_name"],
                p["as_of_date"],
                p["plan_version_label"],
                c["due_total"],
                c["on_time_completed"],
                c["late_completed"],
                c["pending_verification"],
                c["confirmed_overdue_unfinished"],
                c["on_time_rate_pct"],
                c["completion_verification_coverage_pct"],
                p["source_digest"],
            ]
            writer.writerow(
                [
                    "'" + v
                    if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@"))
                    else v
                    for v in values
                ]
            )
        return Response(
            "\ufeff" + output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="evaluation.csv"',
                "Cache-Control": "no-store",
            },
        )

    @app.get("/api/v1/projects/{project_id}/metrics")
    def project_metrics(
        request: Request, project_id: str, db: Db, as_of: date, plan_version_id: str | None = None
    ):
        return ok(
            request, metrics.calculate(db, svc.get(db, Project, project_id), as_of, plan_version_id)
        )

    @app.get("/api/v1/projects/{project_id}/metric-evidence")
    def evidence(
        request: Request,
        project_id: str,
        db: Db,
        as_of: date,
        snapshot_id: str | None = None,
        category: str | None = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ):
        if category and category not in metrics.CATEGORIES:
            svc.fail(422, "INVALID_CATEGORY", "未知评价分类")
        if snapshot_id:
            snap = scoped(db, request.state.principal, MetricSnapshot, snapshot_id)
            if snap.project_id != project_id:
                svc.fail(422, "SNAPSHOT_PROJECT_MISMATCH", "快照不属于本项目")
            payload = snap.payload_json
        else:
            payload = metrics.calculate(db, svc.get(db, Project, project_id), as_of)
        rows = [r for r in payload["evidence"] if not category or r["category"] == category]
        return ok(
            request,
            {
                "source_digest": payload["source_digest"],
                "computed_at": payload["computed_at"],
                "total": len(rows),
                "items": rows[(page - 1) * page_size : page * page_size],
                "page": page,
                "page_size": page_size,
            },
        )

    @app.post("/api/v1/projects/{project_id}/metric-snapshots", status_code=201)
    def snapshot(request: Request, project_id: str, data: SnapshotInput, db: Db):
        obj = metrics.freeze(
            db, svc.get(db, Project, project_id, True), data, request.state.request_id
        )
        db.commit()
        return ok(request, svc.record(obj))

    @app.get("/api/v1/projects/{project_id}/metric-snapshots")
    def snapshots(request: Request, project_id: str, db: Db):
        return ok(
            request,
            [
                {k: v for k, v in svc.record(s).items() if k != "payload_json"}
                for s in db.scalars(
                    select(MetricSnapshot)
                    .where(MetricSnapshot.project_id == project_id)
                    .order_by(MetricSnapshot.created_at.desc())
                )
            ],
        )

    @app.get("/api/v1/metric-snapshots/{snapshot_id}")
    def snapshot_detail(request: Request, snapshot_id: str, db: Db):
        return ok(
            request, svc.record(scoped(db, request.state.principal, MetricSnapshot, snapshot_id))
        )

    @app.get("/api/v1/projects/{project_id}/financial-access")
    def financial_access(request: Request, project_id: str, db: Db):
        svc.get(db, Project, project_id)
        manager = request.state.principal.is_system_admin or bool(
            auth.role(db, request.state.principal, project_id) & {"admin"}
        )
        query = select(FinancialAccess).where(FinancialAccess.project_id == project_id)
        if not manager:
            query = query.where(FinancialAccess.user_id == request.state.principal.user_id)
        return ok(request, [svc.record(a) for a in db.scalars(query)])

    @app.put("/api/v1/projects/{project_id}/financial-access")
    def grant(request: Request, project_id: str, data: FinancialGrant, db: Db):
        svc.get(db, Project, project_id, True)
        if (
            not auth.role(db, request.state.principal, project_id) & {"admin"}
            and not request.state.principal.is_system_admin
        ):
            svc.fail(403, "FORBIDDEN", "需要项目管理员授权")
        if not auth.role(db, SimpleNamespace(user_id=data.user_id), project_id) or not db.scalar(
            select(Credential.id).where(
                Credential.user_id == data.user_id, Credential.enabled.is_(True)
            )
        ):
            svc.fail(422, "INVALID_FINANCIAL_MEMBER", "必须是本项目有可用账号的成员")
        obj = db.scalar(
            select(FinancialAccess).where(
                FinancialAccess.project_id == project_id, FinancialAccess.user_id == data.user_id
            )
        )
        before = svc.record(obj) if obj else None
        if obj is None:
            obj = FinancialAccess(project_id=project_id, user_id=data.user_id)
            db.add(obj)
        for field in ("can_read", "can_write", "can_verify"):
            setattr(obj, field, getattr(data, field))
        svc.audit(db, obj, "grant_financial_access", request.state.request_id, before)
        db.commit()
        return ok(request, svc.record(obj))

    @app.get("/api/v1/projects/{project_id}/financial-records")
    def financial_records(
        request: Request,
        project_id: str,
        db: Db,
        as_of: date,
        direction: Literal["receivable", "payable"] | None = None,
        verification: Literal["submitted", "verified", "returned", "disputed"] | None = None,
    ):
        finance.permission(db, request.state.principal, project_id)
        return ok(request, finance.summary(db, project_id, as_of, direction, verification))

    @app.post("/api/v1/projects/{project_id}/financial-plans", status_code=201)
    def financial_plan(request: Request, project_id: str, data: FinancialPlanInput, db: Db):
        finance.permission(db, request.state.principal, project_id, "write")
        obj = finance.create_plan(
            db, svc.get(db, Project, project_id, True), data, request.state.request_id
        )
        db.commit()
        return ok(request, finance.money_record(obj))

    @app.post("/api/v1/projects/{project_id}/financial-actuals", status_code=201)
    def financial_actual(request: Request, project_id: str, data: FinancialActualInput, db: Db):
        finance.permission(db, request.state.principal, project_id, "write")
        obj = finance.create_actual(
            db, svc.get(db, Project, project_id, True), data, request.state.request_id
        )
        db.commit()
        return ok(request, finance.money_record(obj))

    @app.post("/api/v1/financial-actuals/{financial_actual_id}/verify")
    def verify_financial(
        request: Request,
        financial_actual_id: str,
        data: VerifyInput,
        db: Db,
        if_match: str = Header(),
    ):
        obj = scoped(
            db, request.state.principal, FinancialActual, financial_actual_id, "review", True
        )
        finance.permission(db, request.state.principal, obj.project_id, "verify")
        svc.match(obj, if_match)
        finance.verify(db, obj, data, request.state.request_id)
        db.commit()
        return ok(request, finance.money_record(obj))

    @app.post("/api/v1/projects/{project_id}/reports/draft", status_code=201)
    def draft(
        request: Request,
        project_id: str,
        data: ReportInput,
        db: Db,
        idempotency_key: str = Header(min_length=1, max_length=160),
    ):
        project = svc.get(db, Project, project_id, True)
        snap = scoped(db, request.state.principal, MetricSnapshot, data.metric_snapshot_id)
        if snap.project_id != project_id:
            svc.fail(422, "SNAPSHOT_PROJECT_MISMATCH", "快照不属于本项目")
        obj = reports.generate(db, project, snap, data, idempotency_key, request.state.request_id)
        db.commit()
        return ok(request, reports.detail(db, obj))

    @app.get("/api/v1/projects/{project_id}/reports")
    def report_list(request: Request, project_id: str, db: Db):
        query = select(ReportDraft).where(
            ReportDraft.project_id == project_id, ReportDraft.deleted_at.is_(None)
        )
        if not finance.allowed(db, request.state.principal, project_id):
            query = query.where(ReportDraft.contains_finance.is_(False))
        return ok(
            request,
            [
                {k: v for k, v in svc.record(o).items() if k not in ("content", "fact_bundle_json")}
                for o in db.scalars(query.order_by(ReportDraft.generated_at.desc()))
            ],
        )

    def report_scope(request, db, report_id, action="read", lock=False):
        obj = scoped(db, request.state.principal, ReportDraft, report_id, action, lock)
        reports.check_finance(db, request.state.principal, obj)
        if obj.deleted_at is not None:
            svc.fail(404, "NOT_FOUND", "报告不存在或已删除")
        return obj

    @app.get("/api/v1/reports/{report_id}")
    def report_detail(request: Request, report_id: str, db: Db):
        return ok(request, reports.detail(db, report_scope(request, db, report_id)))

    @app.delete("/api/v1/reports/{report_id}")
    def delete_report(request: Request, report_id: str, db: Db, if_match: str = Header()):
        obj = report_scope(request, db, report_id, "write", True)
        svc.match(obj, if_match)
        reports.remove(db, obj, request.state.request_id)
        db.commit()
        return ok(request, {"id": obj.id})

    @app.post("/api/v1/reports/{report_id}/submit-review")
    def submit_report(request: Request, report_id: str, db: Db, if_match: str = Header()):
        obj = report_scope(request, db, report_id, "write", True)
        svc.match(obj, if_match)
        reports.submit(db, obj, request.state.request_id)
        db.commit()
        return ok(request, reports.detail(db, obj))

    @app.post("/api/v1/reports/{report_id}/review")
    def review_report(
        request: Request, report_id: str, data: ReviewInput, db: Db, if_match: str = Header()
    ):
        obj = report_scope(request, db, report_id, "review", True)
        svc.match(obj, if_match)
        reports.review(db, obj, data, request.state.request_id)
        db.commit()
        return ok(request, reports.detail(db, obj))

    @app.get("/api/v1/reports/{report_id}/export")
    def export_report(request: Request, report_id: str, db: Db, format: Literal["html"] = "html"):
        obj = report_scope(request, db, report_id)
        content = f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>项目阶段报告</title><body><h1>项目阶段报告</h1><p>审核状态：{escape(obj.review_status)} · {escape(obj.generator_type)} · 快照 {escape(obj.metric_snapshot_id)}</p><p>事实摘要 {escape(obj.fact_bundle_json["source_digest"])}</p><pre>{escape(obj.content)}</pre></body></html>'
        return Response(
            content,
            media_type="text/html",
            headers={
                "Content-Disposition": f'attachment; filename="report-{obj.id}.html"',
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.post("/api/v1/notifications/{notification_id}/ai-draft")
    def assist_notice(
        request: Request, notification_id: str, data: AssistInput, db: Db, if_match: str = Header()
    ):
        obj = scoped(db, request.state.principal, Notification, notification_id, "write", True)
        svc.match(obj, if_match)
        wf.live_notice(db, obj)
        if obj.status not in ("draft", "returned"):
            svc.fail(409, "IMMUTABLE_DRAFT", "仅草稿或退回通知可整理")
        original = obj.fact_snapshot_json
        facts = [
            {
                "id": "NOTICE_BASIS",
                "section": "overview",
                "kind": "notification_basis",
                "text": f"{original['project_code']} · {original['project_name']}；{original['milestone_code']} {original['milestone_name']}；计划 {original['plan_version']}，日期 {original['planned_date']}。",
            },
            {
                "id": "NOTICE_RECIPIENT",
                "section": "overview",
                "kind": "recipient",
                "text": f"接收人 {original['recipient_name']}；提醒日期 {original['trigger_date']}，规则 {original['rule_code']} / {original['rule_version']}。",
            },
        ]
        for index, action in enumerate(original["actions"]):
            facts.append(
                {
                    "id": f"ACTION_{index + 1}",
                    "section": "attention",
                    "kind": "approved_action",
                    "text": f"{action['title']}；完成判定及核实依据：{action['completion_criteria']}。",
                }
            )
        arranged, meta = ai_service.arrange(
            facts, data.allow_external, db=db, scenario="notification"
        )
        before = svc.record(obj)
        obj.body = ai_service.render(facts, arranged, "节点工作通知草稿", meta)
        obj.status = "draft"
        obj.draft_version += 1
        obj.editor_ids = sorted(set(obj.editor_ids + [request.state.principal.user_id]))
        svc.audit(db, obj, "ai_arrange_draft", request.state.request_id, before)
        db.commit()
        return ok(request, {"notice": wf.notification_detail(db, obj), "generation": meta})
