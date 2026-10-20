"""Reports render only immutable, cited facts; model output cannot introduce prose facts."""

from sqlalchemy import select

from . import ai_service, finance
from .evaluation_models import ReportDraft, ReportReview
from .metrics import digest
from .models import now
from .services import audit, fail, record


def bundle(snapshot, financial=None, report_type="stage"):
    payload = snapshot.payload_json
    counts = payload["counts"]
    facts = [
        {
            "id": "BASIS",
            "section": "overview",
            "kind": "basis",
            "text": f"项目 {payload['project_code']} · {payload['project_name']}；业务截止日 {payload['as_of_date']}；计划 {payload['plan_version_label']}；公式 trial_v1；计算时间 {payload['computed_at']}。",
        },
        {
            "id": "COUNTS",
            "section": "overview",
            "kind": "counts",
            "text": f"应完成 {counts['due_total']}，按期完成 {counts['on_time_completed']}，延期完成 {counts['late_completed']}，待核对 {counts['pending_verification']}，已核实逾期未完成 {counts['confirmed_overdue_unfinished']}。",
        },
        {
            "id": "RATE",
            "section": "overview",
            "kind": "rate",
            "text": f"试算按期率 {counts['on_time_rate_pct'] or '无分母'}%；完成事实核实覆盖率 {counts['completion_verification_coverage_pct'] or '无分母'}%；不生成综合得分。",
        },
    ]
    exceptions = [
        e
        for e in payload["evidence"]
        if e["category"]
        in ("late_completed", "pending_verification", "confirmed_overdue_unfinished")
    ]
    for i, e in enumerate(exceptions[:80]):
        facts.append(
            {
                "id": f"NODE_{i + 1}",
                "section": "attention",
                "kind": e["category"],
                "milestone_id": e["milestone_id"],
                "plan_item_id": e["plan_item_id"],
                "verified_actual_id": e["verified_actual_id"],
                "source_ref": e["source_ref"],
                "text": f"{e['milestone_code']} {e['milestone_name']}：计划 {e['planned_date']}；已核实实际日期 {e['actual_date'] or '暂无'}；偏差 {e['deviation_days'] if e['deviation_days'] is not None else '不计算'} 天。{e['reason']}。计划来源：{e['source_ref']}。",
            }
        )
    if len(exceptions) > 80:
        facts.append(
            {
                "id": "MORE_NODES",
                "section": "attention",
                "kind": "additional_evidence",
                "text": f"其余 {len(exceptions) - 80} 条异常详见冻结快照完整节点证据，正文仅展示前80条。",
            }
        )
    if not exceptions:
        facts.append(
            {
                "id": "NO_EXCEPTION",
                "section": "attention",
                "kind": "scope",
                "text": "本次口径未检出延期完成、待核对或已核实逾期未完成节点；不代表其他风险不存在。",
            }
        )
    if financial:
        for i, g in enumerate(financial["groups"]):
            facts.append(
                {
                    "id": f"FIN_{i + 1}",
                    "section": "overview",
                    "kind": "financial_summary",
                    "financial": True,
                    "text": f"{g['currency']} {g['direction']}：计划总额 {g['planned_total']}；到期计划 {g['planned_due_total']}；已核实实际 {g['verified_actual_total'] if g['verified_actual_total'] is not None else '待核实'}，已核实记录 {g['verified_count']}。计划与实际独立，台账完整性未经证明。",
                }
            )
        if len(facts) > 180:
            fail(422, "REPORT_TOO_LARGE", "财务分组过多，请分别生成报告")
    return {
        "metric_snapshot_id": snapshot.id,
        "source_digest": snapshot.source_digest,
        "metric_payload": payload,
        "finance": financial,
        "report_type": report_type,
        "facts": facts,
    }


def detail(db, obj):
    return {
        **record(obj),
        "reviews": [
            record(r)
            for r in db.scalars(
                select(ReportReview)
                .where(ReportReview.report_id == obj.id)
                .order_by(ReportReview.reviewed_at)
            )
        ],
    }


def check_finance(db, principal, obj):
    if obj.contains_finance:
        finance.permission(db, principal, obj.project_id)


def generate(db, project, snapshot, data, key, request_id):
    request_digest = digest(data.model_dump(mode="json"))
    existing = db.scalar(
        select(ReportDraft).where(
            ReportDraft.project_id == project.id, ReportDraft.request_key == key
        )
    )
    if existing:
        check_finance(db, db.info["principal"], existing)
        if existing.request_digest != request_digest:
            fail(409, "IDEMPOTENCY_CONFLICT", "幂等键已用于另一生成请求")
        return existing
    if data.include_finance:
        finance.permission(db, db.info["principal"], project.id)
    financial = (
        finance.summary(db, project.id, snapshot.as_of_date) if data.include_finance else None
    )
    facts = bundle(snapshot, financial, data.report_type)
    arranged, meta = ai_service.arrange(facts["facts"], data.allow_external)
    content = ai_service.render(
        facts["facts"],
        arranged,
        {
            "stage": "项目阶段评价报告",
            "exceptions": "异常节点分析报告",
            "work_plan": "阶段工作安排",
        }[data.report_type],
        meta,
    )
    obj = ReportDraft(
        project_id=project.id,
        metric_snapshot_id=snapshot.id,
        request_key=key,
        request_digest=request_digest,
        report_type=data.report_type,
        fact_bundle_json=facts,
        generator_type=meta["generator_type"],
        model_id=meta["model_id"],
        content=content,
        validation_json={**meta, "fact_references_valid": True, "content_digest": digest(content)},
        contains_finance=data.include_finance,
        created_by=db.info["actor_id"],
        editor_ids=[db.info["actor_id"]],
    )
    db.add(obj)
    audit(db, obj, "generate_report", request_id)
    return obj


def submit(db, obj, request_id):
    if obj.review_status not in ("draft", "returned"):
        fail(409, "INVALID_STATE_TRANSITION", "仅草稿或退回报告可提交")
    before = record(obj)
    obj.review_status = "pending_review"
    obj.editor_ids = sorted(set(obj.editor_ids + [db.info["actor_id"]]))
    audit(db, obj, "submit_report", request_id, before)


def review(db, obj, data, request_id):
    if db.info["actor_id"] in obj.editor_ids:
        fail(403, "SELF_REVIEW_FORBIDDEN", "报告编制与提交人不能审核自己的报告")
    if obj.review_status != "pending_review":
        fail(409, "INVALID_STATE_TRANSITION", "报告未待审核或已处理")
    before = record(obj)
    obj.review_status = data.decision
    obj.reviewer_id = db.info["actor_id"]
    obj.reviewed_at = now()
    db.add(
        ReportReview(
            report_id=obj.id,
            decision=data.decision,
            comment=data.comment,
            reviewer_id=db.info["actor_id"],
            content_digest=digest(obj.content),
        )
    )
    audit(db, obj, "review_report", request_id, before)
