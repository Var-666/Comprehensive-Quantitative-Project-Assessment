from fastapi import Header, Request
from sqlalchemy import select

from . import llm_settings as service
from .config import settings
from .llm_models import SERVICE_ID, LLMCallLog, LLMConfig
from .llm_schemas import (
    CredentialInput,
    EnvironmentImport,
    ManualModelInput,
    ModelChoice,
    ModelUpdate,
    ScenarioChoices,
    ServiceInput,
)
from .models import AuditEvent
from .services import fail, record


def admin(request):
    if not request.state.principal.is_system_admin:
        fail(403, "SYSTEM_ADMIN_REQUIRED", "仅系统管理员可管理大模型配置")


def credential_transport_allowed(request):
    return request.url.scheme == "https" or (
        settings.llm_allow_local_http_credentials
        and settings.app_env in ("development", "test")
        and request.url.scheme == "http"
        and request.url.hostname in ("127.0.0.1", "localhost", "::1")
        and request.client is not None
        and request.client.host in ("127.0.0.1", "::1")
    )


def require_credential_transport(request):
    if not credential_transport_allowed(request):
        fail(
            400,
            "LLM_HTTPS_REQUIRED",
            "密钥配置需HTTPS；开发环境只有显式启用的本机HTTP入口可例外使用",
        )


def register(app, Db, ok):
    @app.get("/api/v1/settings/llm")
    def get_settings(request: Request, db: Db):
        admin(request)
        return ok(request, service.public_config(db))

    @app.put("/api/v1/settings/llm")
    def save(request: Request, data: ServiceInput, db: Db, if_match: str = Header()):
        admin(request)
        obj = service.save(db, data, if_match, request.state.request_id)
        db.commit()
        return ok(request, service.public_config(db, obj))

    @app.put("/api/v1/settings/llm/credential")
    def credential(request: Request, data: CredentialInput, db: Db, if_match: str = Header()):
        admin(request)
        require_credential_transport(request)
        obj = service.replace_key(db, data, if_match, request.state.request_id)
        db.commit()
        return ok(request, service.public_config(db, obj))

    @app.delete("/api/v1/settings/llm/credential")
    def remove(request: Request, db: Db, if_match: str = Header()):
        admin(request)
        require_credential_transport(request)
        obj = service.remove_key(db, if_match, request.state.request_id)
        db.commit()
        return ok(request, service.public_config(db, obj))

    @app.post("/api/v1/settings/llm/import-environment")
    def import_environment(
        request: Request, data: EnvironmentImport, db: Db, if_match: str = Header()
    ):
        admin(request)
        require_credential_transport(request)
        obj = service.import_environment(db, if_match, request.state.request_id)
        db.commit()
        return ok(request, service.public_config(db, obj))

    @app.get("/api/v1/settings/llm/models")
    def model_list(request: Request, db: Db):
        admin(request)
        obj = db.get(LLMConfig, SERVICE_ID)
        return ok(request, [service.public_model(m, obj) for m in service.models(db, obj)])

    @app.post("/api/v1/settings/llm/test-connection")
    def test_connection(request: Request, db: Db, if_match: str = Header()):
        admin(request)
        obj = service.lock(db, if_match)
        result = service.test_connection(db, obj, request.state.request_id)
        db.commit()
        return ok(request, {"result": result, "config": service.public_config(db, obj)})

    @app.post("/api/v1/settings/llm/models/refresh")
    def refresh(request: Request, db: Db, if_match: str = Header()):
        admin(request)
        obj = service.lock(db, if_match)
        result = service.test_connection(db, obj, request.state.request_id, True)
        db.commit()
        return ok(
            request,
            {
                "result": result,
                "config": service.public_config(db, obj),
                "models": [service.public_model(m, obj) for m in service.models(db, obj)],
            },
        )

    @app.post("/api/v1/settings/llm/models", status_code=201)
    def add_model(request: Request, data: ManualModelInput, db: Db, if_match: str = Header()):
        admin(request)
        obj = service.lock(db, if_match)
        model = service.add_model(db, obj, data, request.state.request_id)
        db.commit()
        return ok(request, service.public_model(model, obj))

    @app.put("/api/v1/settings/llm/models/{model_config_id}")
    def update_model(
        request: Request, model_config_id: str, data: ModelUpdate, db: Db, if_match: str = Header()
    ):
        admin(request)
        obj = service.lock(db)
        model = service.model_scope(db, obj, model_config_id)
        service.mutate_model(db, model, if_match, request.state.request_id, enabled=data.enabled)
        db.commit()
        return ok(request, service.public_model(model, obj))

    @app.delete("/api/v1/settings/llm/models/{model_config_id}")
    def delete_model(request: Request, model_config_id: str, db: Db, if_match: str = Header()):
        admin(request)
        obj = service.lock(db)
        model = service.model_scope(db, obj, model_config_id)
        service.mutate_model(db, model, if_match, request.state.request_id, delete=True)
        db.commit()
        return ok(request, {"deleted": True})

    @app.post("/api/v1/settings/llm/models/{model_config_id}/test")
    def test_model(request: Request, model_config_id: str, db: Db, if_match: str = Header()):
        admin(request)
        obj = service.lock(db)
        model = service.model_scope(db, obj, model_config_id)
        from .services import match

        match(model, if_match)
        result = service.test_model(db, obj, model, request.state.request_id)
        db.commit()
        return ok(request, {"result": result, "model": service.public_model(model, obj)})

    @app.put("/api/v1/settings/llm/default-model")
    def default_model(request: Request, data: ModelChoice, db: Db, if_match: str = Header()):
        admin(request)
        obj = service.lock(db, if_match)
        service.choose(db, obj, "default", data.model_config_id, request.state.request_id)
        db.commit()
        return ok(request, service.public_config(db, obj))

    @app.put("/api/v1/settings/llm/scenario-models")
    def scenarios(request: Request, data: ScenarioChoices, db: Db, if_match: str = Header()):
        admin(request)
        obj = service.lock(db, if_match)
        for scenario, key in data.model_dump().items():
            service.choose(db, obj, scenario, key, request.state.request_id)
        db.commit()
        return ok(request, service.public_config(db, obj))

    @app.get("/api/v1/settings/llm/audit-events")
    def audit_events(request: Request, db: Db):
        admin(request)
        return ok(
            request,
            [
                record(e)
                for e in db.scalars(
                    select(AuditEvent)
                    .where(AuditEvent.aggregate_type.in_(["llm_service_config", "llm_models"]))
                    .order_by(AuditEvent.occurred_at.desc())
                    .limit(100)
                )
            ],
        )

    @app.get("/api/v1/settings/llm/call-logs")
    def call_logs(request: Request, db: Db):
        admin(request)
        return ok(
            request,
            [
                record(e)
                for e in db.scalars(
                    select(LLMCallLog).order_by(LLMCallLog.occurred_at.desc()).limit(100)
                )
            ],
        )
