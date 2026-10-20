import csv
import io
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import auth, auth_routes, evaluation_routes, imports, llm_routes, workflow_routes
from . import services as svc
from .config import PENDING_RULES, settings
from .db import get_db
from .models import (
    ActualRecord,
    AuditEvent,
    Department,
    ImportBatch,
    Milestone,
    NodeType,
    PlanItem,
    PlanVersion,
    Project,
    User,
    now,
)
from .schemas import (
    ActivateInput,
    ActualInput,
    CommitInput,
    MilestoneInput,
    PlanCreate,
    ProjectInput,
    VerifyInput,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("project-api")


@asynccontextmanager
async def lifespan(_):
    if settings.app_env == "production" and (
        settings.demo_mode
        or not settings.cookie_secure
        or not settings.database_url.startswith("postgresql")
    ):
        raise RuntimeError("正式环境必须使用PostgreSQL、HTTPS安全Cookie并关闭模拟数据模式")
    yield


app = FastAPI(
    title="项目总体量化评估智能体",
    version="0.4.0",
    lifespan=lifespan,
    dependencies=[Depends(auth.authorize)],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = str(uuid4())
    start = time.monotonic()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    logger.info(
        "%s %s status=%s request_id=%s duration_ms=%.1f",
        request.method,
        request.url.path,
        response.status_code,
        request.state.request_id,
        (time.monotonic() - start) * 1000,
    )
    return response


def error(request, status, detail):
    return JSONResponse(
        status_code=status,
        content={
            "success": False,
            "error": detail,
            "meta": {"request_id": getattr(request.state, "request_id", "unknown")},
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    detail = (
        exc.detail
        if isinstance(exc.detail, dict)
        else {"code": "HTTP_ERROR", "message": str(exc.detail), "fields": [], "retryable": False}
    )
    return error(request, exc.status_code, detail)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return error(
        request,
        422,
        {
            "code": "VALIDATION_ERROR",
            "message": "参数校验失败",
            "fields": [
                {"field": ".".join(map(str, e["loc"])), "reason": e["msg"]} for e in exc.errors()
            ],
            "retryable": False,
        },
    )


@app.exception_handler(IntegrityError)
async def integrity_error(request, exc):
    return error(
        request,
        409,
        {
            "code": "CONSTRAINT_CONFLICT",
            "message": "数据约束冲突或编号已存在，事务已回滚",
            "fields": [],
            "retryable": False,
        },
    )


@app.exception_handler(StaleDataError)
async def stale_error(request, exc):
    return error(
        request,
        409,
        {
            "code": "STALE_VERSION",
            "message": "数据已被修改，请刷新后重试",
            "fields": [],
            "retryable": False,
        },
    )


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    logger.exception("Unhandled request_id=%s", request.state.request_id)
    return error(
        request,
        500,
        {
            "code": "INTERNAL_ERROR",
            "message": "服务异常，请凭请求编号检查日志",
            "fields": [],
            "retryable": False,
        },
    )


def ok(request, data):
    return {
        "success": True,
        "data": data,
        "meta": {
            "request_id": request.state.request_id,
            "mode": "sample" if settings.demo_mode else "business",
            "timezone": settings.business_timezone,
        },
    }


Db = Annotated[Session, Depends(get_db)]
auth_routes.register(app, Db, ok)
workflow_routes.register(app, Db, ok)
evaluation_routes.register(app, Db, ok)
llm_routes.register(app, Db, ok)


@app.get("/api/v1/health")
def health(request: Request, db: Db):
    db.execute(text("SELECT 1"))
    return ok(request, {"status": "ok", "mode": "local_demo"})


@app.get("/api/v1/config")
def config(request: Request):
    return ok(
        request,
        {
            "pending_rules": PENDING_RULES,
            "partial_import_enabled": False,
            "project_statuses": ["draft", "not_started", "active", "completed", "archived"],
            "identity": request.state.principal.display_name,
            "demo_mode": settings.demo_mode,
        },
    )


@app.get("/api/v1/departments")
def departments(request: Request, db: Db):
    return ok(
        request,
        [svc.record(x) for x in db.scalars(select(Department).order_by(Department.dept_name))],
    )


@app.get("/api/v1/users")
def users(request: Request, db: Db):
    return ok(
        request, [svc.record(x) for x in db.scalars(select(User).order_by(User.display_name))]
    )


@app.get("/api/v1/dictionaries/node-types")
def node_types(request: Request, db: Db):
    return ok(
        request, [svc.record(x) for x in db.scalars(select(NodeType).order_by(NodeType.code))]
    )


@app.get("/api/v1/projects")
def projects(
    request: Request,
    db: Db,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    type: str | None = None,
    keyword: str | None = None,
):
    query = select(Project)
    query = query.where(Project.id.in_(auth.visible_projects(request.state.principal)))
    if status:
        query = query.where(Project.project_status == status)
    if type:
        query = query.where(Project.project_type == type)
    if keyword:
        query = query.outerjoin(User, Project.owner_id == User.id).where(
            or_(
                Project.project_code.contains(keyword, autoescape=True),
                Project.project_name.contains(keyword, autoescape=True),
                User.display_name.contains(keyword, autoescape=True),
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(
        query.order_by(Project.updated_at.desc(), Project.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok(
        request,
        {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [svc.project_detail(db, p) for p in items],
        },
    )


@app.get("/api/v1/summary")
def summary(request: Request, db: Db):
    visible = auth.visible_projects(request.state.principal)
    counts = dict(
        db.execute(
            select(Project.project_status, func.count())
            .where(Project.id.in_(visible))
            .group_by(Project.project_status)
        ).all()
    )
    return ok(
        request,
        {
            "total": sum(counts.values()),
            "active": counts.get("active", 0),
            "draft": counts.get("draft", 0),
            "completed": counts.get("completed", 0),
            "milestones": db.scalar(
                select(func.count()).select_from(Milestone).where(Milestone.project_id.in_(visible))
            ),
        },
    )


@app.post("/api/v1/projects", status_code=201)
def create_project(request: Request, data: ProjectInput, db: Db):
    project = svc.create_project(db, data, request.state.request_id)
    db.commit()
    return ok(request, svc.project_detail(db, project))


@app.get("/api/v1/projects/{project_id}")
@app.get("/api/v1/projects/{project_id}/overview")
def project_detail(request: Request, project_id: str, db: Db):
    return ok(request, svc.project_detail(db, svc.get(db, Project, project_id)))


@app.patch("/api/v1/projects/{project_id}")
def edit_project(
    request: Request, project_id: str, data: ProjectInput, db: Db, if_match: str = Header()
):
    obj = svc.update_project(db, project_id, data, if_match, request.state.request_id)
    db.commit()
    return ok(request, svc.project_detail(db, obj))


@app.delete("/api/v1/projects/{project_id}")
def archive_project(request: Request, project_id: str, db: Db, if_match: str = Header()):
    obj = svc.get(db, Project, project_id, True)
    svc.match(obj, if_match)
    before = svc.record(obj)
    obj.project_status = "archived"
    from .workflow import invalidate_plan

    invalidate_plan(db, obj.id, "项目归档", request.state.request_id)
    obj.row_version += 1
    svc.audit(db, obj, "archive", request.state.request_id, before)
    db.commit()
    return ok(request, svc.project_detail(db, obj))


@app.get("/api/v1/projects/{project_id}/plan-versions")
def plans(request: Request, project_id: str, db: Db):
    svc.get(db, Project, project_id)
    return ok(
        request,
        [
            svc.record(p)
            for p in db.scalars(
                select(PlanVersion)
                .where(PlanVersion.project_id == project_id)
                .order_by(PlanVersion.created_at.desc())
            )
        ],
    )


@app.post("/api/v1/projects/{project_id}/plan-versions", status_code=201)
def new_plan(request: Request, project_id: str, data: PlanCreate, db: Db, if_match: str = Header()):
    obj = svc.create_plan(db, project_id, data, if_match, request.state.request_id)
    db.commit()
    return ok(request, svc.record(obj))


@app.post("/api/v1/plan-versions/{version_id}/activate")
def activate_plan(
    request: Request, version_id: str, data: ActivateInput, db: Db, if_match: str = Header()
):
    obj = svc.activate_plan(db, version_id, if_match, data.approval_ref, request.state.request_id)
    db.commit()
    return ok(request, svc.record(obj))


@app.get("/api/v1/projects/{project_id}/milestones")
def milestones(
    request: Request,
    project_id: str,
    db: Db,
    plan_version_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=100),
    type: str | None = None,
    department: str | None = None,
):
    project = svc.get(db, Project, project_id)
    if not plan_version_id:
        plan_version_id = project.current_plan_version_id or db.scalar(
            select(PlanVersion.id)
            .where(PlanVersion.project_id == project_id)
            .order_by(PlanVersion.created_at.desc())
        )
    plan = svc.get(db, PlanVersion, plan_version_id)
    if plan.project_id != project_id:
        svc.fail(422, "PLAN_PROJECT_MISMATCH", "版本不属于该项目")
    query = (
        select(Milestone)
        .join(PlanItem, Milestone.id == PlanItem.milestone_id)
        .where(
            Milestone.project_id == project_id,
            PlanItem.plan_version_id == plan_version_id,
            PlanItem.is_included.is_(True),
        )
    )
    if type:
        query = query.where(PlanItem.node_type_code == type)
    if department:
        query = query.where(PlanItem.department_id == department)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    nodes = db.scalars(
        query.order_by(PlanItem.planned_date, Milestone.milestone_code)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok(
        request,
        {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [svc.milestone_detail(db, n, plan_version_id) for n in nodes],
        },
    )


@app.post("/api/v1/projects/{project_id}/milestones", status_code=201)
def new_milestone(request: Request, project_id: str, data: MilestoneInput, db: Db):
    node = svc.create_milestone(db, project_id, data, request.state.request_id)
    db.commit()
    return ok(request, svc.milestone_detail(db, node, data.plan_version_id))


@app.get("/api/v1/milestones/{milestone_id}")
def milestone(request: Request, milestone_id: str, db: Db, plan_version_id: str | None = None):
    result = svc.milestone_detail(db, svc.get(db, Milestone, milestone_id), plan_version_id)
    result["history"] = [
        svc.record(p)
        for p in db.scalars(
            select(PlanItem)
            .where(PlanItem.milestone_id == milestone_id)
            .order_by(PlanItem.plan_version_id)
        )
    ]
    item_ids = [p["id"] for p in result["history"]]
    actual_ids = [p["id"] for p in result["actual_records"]]
    result["audit_events"] = [
        svc.record(e)
        for e in db.scalars(
            select(AuditEvent)
            .where(AuditEvent.aggregate_id.in_([milestone_id, *item_ids, *actual_ids]))
            .order_by(AuditEvent.occurred_at.desc())
        )
    ]
    return ok(request, result)


@app.patch("/api/v1/milestones/{milestone_id}/plan-item")
def edit_node(
    request: Request, milestone_id: str, data: MilestoneInput, db: Db, if_match: str = Header()
):
    node = svc.update_milestone(db, milestone_id, data, if_match, request.state.request_id)
    db.commit()
    return ok(request, svc.milestone_detail(db, node, data.plan_version_id))


@app.post("/api/v1/milestones/{milestone_id}/actuals", status_code=201)
def actual(request: Request, milestone_id: str, data: ActualInput, db: Db):
    node = svc.get(db, Milestone, milestone_id, True)
    node.row_version += 1
    obj = ActualRecord(
        milestone_id=node.id, submitted_by=request.state.principal.user_id, **data.model_dump()
    )
    db.add(obj)
    svc.audit(db, obj, "submit_actual", request.state.request_id)
    db.commit()
    return ok(request, svc.record(obj))


@app.post("/api/v1/milestone-actuals/{actual_id}/verify")
def verify_actual(request: Request, actual_id: str, data: VerifyInput, db: Db):
    obj = svc.get(db, ActualRecord, actual_id)
    node = svc.get(db, Milestone, obj.milestone_id)
    svc.get(db, Project, node.project_id, True)
    node = svc.get(db, Milestone, obj.milestone_id, True)
    db.refresh(obj)
    if obj.submitted_by == request.state.principal.user_id:
        svc.fail(403, "SELF_VERIFICATION_FORBIDDEN", "实际提交人不能核实自己的记录")
    if obj.verification_status != "submitted":
        svc.fail(409, "ALREADY_REVIEWED", "该记录已处理，需重新提交新的实际记录")
    before = svc.record(obj)
    if data.decision == "verified":
        for old in db.scalars(
            select(ActualRecord).where(
                ActualRecord.milestone_id == node.id, ActualRecord.is_current.is_(True)
            )
        ):
            old_before = svc.record(old)
            old.is_current = False
            svc.audit(db, old, "supersede_fact", request.state.request_id, old_before)
        db.flush()
        obj.is_current = True
        if obj.completion_flag:
            from .workflow import invalidate
            from .workflow_models import Reminder

            item_ids = select(PlanItem.id).where(PlanItem.milestone_id == node.id)
            invalidate(
                db,
                select(Reminder).where(Reminder.milestone_plan_item_id.in_(item_ids)),
                "节点已核实完成",
                request.state.request_id,
            )
    obj.verification_status = data.decision
    obj.verified_at = now()
    obj.verified_by = request.state.principal.user_id
    obj.comment = data.comment
    node.row_version += 1
    svc.audit(db, obj, "verify", request.state.request_id, before)
    db.commit()
    return ok(request, svc.record(obj))


@app.get("/api/v1/projects/{project_id}/audit-events")
def project_audit(request: Request, project_id: str, db: Db):
    svc.get(db, Project, project_id)
    plan_ids = select(PlanVersion.id).where(PlanVersion.project_id == project_id)
    return ok(
        request,
        [
            svc.record(e)
            for e in db.scalars(
                select(AuditEvent)
                .where(
                    or_(
                        AuditEvent.aggregate_id == project_id, AuditEvent.aggregate_id.in_(plan_ids)
                    )
                )
                .order_by(AuditEvent.occurred_at.desc())
            )
        ],
    )


@app.post("/api/v1/imports/preview", status_code=201)
async def import_preview(
    request: Request,
    db: Db,
    file: UploadFile = File(),
    target: str = Form("projects"),
    mapping_json: str = Form("{}"),
    sheet_name: str = Form(""),
    header_row: int = Form(1, ge=1, le=50),
    project_id: str | None = Form(None),
    plan_version_id: str | None = Form(None),
):
    content = await file.read(settings.max_upload_bytes + 1)
    if target == "projects" and not request.state.principal.is_system_admin:
        svc.fail(403, "FORBIDDEN", "仅系统管理员可导入项目")
    if target == "milestones":
        svc.get(db, Project, project_id)
        auth.require_project(db, request.state.principal, project_id, "write")
    try:
        mapping = json.loads(mapping_json)
    except json.JSONDecodeError:
        svc.fail(422, "INVALID_MAPPING_JSON", "字段映射 JSON 无效")
    if not isinstance(mapping, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()
    ):
        svc.fail(422, "INVALID_MAPPING", "字段映射必须为系统字段到 Excel 列名的对象")
    batch = imports.preview(
        db,
        content,
        file.filename or "",
        target,
        mapping,
        sheet_name,
        header_row,
        {"project_id": project_id, "plan_version_id": plan_version_id},
        request.state.request_id,
    )
    db.commit()
    return ok(request, imports.batch_detail(db, batch))


@app.get("/api/v1/imports/{batch_id}")
def import_detail(request: Request, batch_id: str, db: Db):
    return ok(request, imports.batch_detail(db, svc.get(db, ImportBatch, batch_id)))


@app.post("/api/v1/imports/{batch_id}/commit")
def import_commit(
    request: Request,
    batch_id: str,
    data: CommitInput,
    db: Db,
    idempotency_key: str = Header(min_length=1, max_length=160),
):
    try:
        batch = imports.commit(db, batch_id, data, idempotency_key, request.state.request_id)
        db.commit()
    except HTTPException as exc:
        db.rollback()
        # Retain failed confirmation attempts without keeping any business writes.
        if db.get(ImportBatch, batch_id):
            db.add(
                AuditEvent(
                    aggregate_type="import_batches",
                    aggregate_id=batch_id,
                    action="commit_rejected",
                    after_json=exc.detail,
                    request_id=request.state.request_id,
                )
            )
            db.commit()
        raise
    return ok(request, imports.batch_detail(db, batch))


@app.get("/api/v1/imports/{batch_id}/errors")
def import_errors(batch_id: str, db: Db):
    detail = imports.batch_detail(db, svc.get(db, ImportBatch, batch_id))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["sheet", "row", "status", "errors"])
    for row in detail["rows"]:
        if row["validation_errors_json"]:
            values = [
                row["sheet_name"],
                row["source_row_number"],
                row["row_status"],
                json.dumps(row["validation_errors_json"], ensure_ascii=False),
            ]
            writer.writerow(
                [
                    "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v
                    for v in values
                ]
            )
    return Response(
        "\ufeff" + output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=import-errors.csv"},
    )
