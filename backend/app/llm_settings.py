"""Administrator configuration operations and explicit environment migration."""

from fastapi import HTTPException
from sqlalchemy import select

from .config import settings
from .llm_models import DEFAULT_BASE_URL, SERVICE_ID, LLMConfig, LLMModel, LLMSelection
from .llm_provider import ProviderError, validate_base_url
from .llm_secrets import CredentialVault
from .llm_service import LLMService
from .models import AuditEvent, now
from .services import fail, get, match, record


def public_config(db, obj=None):
    obj = obj or db.get(LLMConfig, SERVICE_ID)
    transport = {
        "local_http_credentials_enabled": settings.llm_allow_local_http_credentials
        and settings.app_env in ("development", "test")
    }
    try:
        CredentialVault.cipher()
        encryption_ready = True
    except HTTPException:
        encryption_ready = False
    if obj:
        return {
            **transport,
            "id": obj.id,
            "source": "database",
            "service_name": obj.service_name,
            "base_url": obj.base_url,
            "adapter": obj.adapter,
            "mode": obj.mode,
            "enabled": obj.enabled,
            "timeout_seconds": obj.timeout_seconds,
            "key_configured": bool(obj.encrypted_api_key),
            "credential_source": "database" if obj.encrypted_api_key else "removed_or_unconfigured",
            "credential_updated_at": record(obj)["credential_updated_at"],
            "revision": obj.revision,
            "endpoint_revision": obj.endpoint_revision,
            "last_connection_test": obj.last_connection_test,
            "last_models_refresh": obj.last_models_refresh,
            "row_version": obj.row_version,
            "updated_at": record(obj)["updated_at"],
            "encryption_ready": encryption_ready,
            "environment_available": LLMService.legacy_configured(),
            "selections": LLMService.selections(db),
        }
    # Never render credentials embedded in legacy URLs, even when deployment config was invalid.
    legacy_warning = None
    try:
        base = validate_base_url(settings.ai_base_url or DEFAULT_BASE_URL, allow_unlisted=True)
        if (
            settings.ai_api_key.get_secret_value()
            and settings.ai_api_key.get_secret_value() in base
        ):
            base = DEFAULT_BASE_URL
            legacy_warning = "旧环境地址含凭据信息，已隐藏；请重新配置安全地址。"
        else:
            try:
                validate_base_url(base)
            except HTTPException:
                legacy_warning = (
                    "旧环境地址未列入新部署白名单；请运维明确批准该origin后再迁移或调用。"
                )
    except HTTPException:
        base = DEFAULT_BASE_URL
        legacy_warning = "旧环境地址未通过安全校验，当前显示预置候选地址；请重新配置。"
    return {
        **transport,
        "id": SERVICE_ID,
        "source": "environment" if LLMService.legacy_configured() else "defaults",
        "legacy_warning": legacy_warning,
        "service_name": "企业 MaaS 网关（自定义）",
        "base_url": base,
        "adapter": "openai_compatible",
        "mode": "mock" if settings.ai_provider == "mock" else "maas",
        "enabled": settings.ai_provider != "mock" and settings.ai_external_enabled,
        "timeout_seconds": int(settings.ai_timeout_seconds),
        "key_configured": bool(settings.ai_api_key.get_secret_value()),
        "credential_source": "environment"
        if settings.ai_api_key.get_secret_value()
        else "unconfigured",
        "credential_updated_at": None,
        "revision": 0,
        "endpoint_revision": 0,
        "last_connection_test": None,
        "last_models_refresh": None,
        "row_version": 0,
        "updated_at": None,
        "encryption_ready": encryption_ready,
        "environment_available": LLMService.legacy_configured(),
        "selections": {},
    }


def audit(db, obj, action, request_id, before=None, extra=None):
    db.flush()
    snapshot = public_config(db, obj) if isinstance(obj, LLMConfig) else record(obj)
    # A deliberate allowlisted snapshot: encrypted credential material never enters generic audit.
    db.add(
        AuditEvent(
            aggregate_type=obj.__tablename__,
            aggregate_id=obj.id,
            action=action,
            before_json=before,
            after_json={**snapshot, **(extra or {})},
            actor_id=db.info["actor_id"],
            request_id=request_id,
        )
    )


def lock(db, version=None, replace_environment=False):
    obj = db.scalar(
        select(LLMConfig)
        .where(LLMConfig.id == SERVICE_ID)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if obj:
        if version is not None:
            match(obj, version)
        return obj
    if version is not None and version != "0":
        fail(409, "STALE_VERSION", "配置已变化，请刷新")
    if LLMService.legacy_configured() and not replace_environment:
        fail(
            409,
            "LLM_ENVIRONMENT_CONFIRMATION_REQUIRED",
            "旧环境配置仍在生效；请显式确认接管或使用迁移功能，不能静默覆盖",
        )
    obj = LLMConfig(
        id=SERVICE_ID,
        service_name="企业 MaaS 网关（自定义）",
        base_url=public_config(db)["base_url"],
        mode="mock",
        enabled=False,
        updated_by=db.info["actor_id"],
    )
    db.add(obj)
    db.flush()
    return obj


def changed_credentials(db, obj):
    obj.revision += 1
    obj.last_connection_test = None
    obj.last_models_refresh = None
    for model in db.scalars(
        select(LLMModel).where(
            LLMModel.service_id == obj.id, LLMModel.endpoint_revision == obj.endpoint_revision
        )
    ):
        model.verification_status = "untested"
    obj.updated_by = db.info["actor_id"]


def save(db, data, version, request_id):
    base = validate_base_url(data.base_url)
    obj = lock(db, version, data.replace_environment)
    before = public_config(db, obj)
    if obj.encrypted_api_key and (base != obj.base_url or data.service_name != obj.service_name):
        secret = CredentialVault.decrypt(obj.encrypted_api_key).get_secret_value()
        if secret in base or secret in data.service_name:
            fail(422, "LLM_CREDENTIAL_PUBLIC_VALUE_CONFLICT", "服务名称和地址不能包含凭据")
    endpoint_changed = base != obj.base_url
    requested_enabled = data.enabled and not endpoint_changed
    if endpoint_changed:
        for choice in db.scalars(select(LLMSelection).where(LLMSelection.service_id == obj.id)):
            db.delete(choice)
        db.flush()
        obj.base_url = base
        obj.endpoint_revision += 1
        obj.encrypted_api_key = None
        obj.credential_updated_at = now()
        obj.enabled = False
        changed_credentials(db, obj)
    for name in ("service_name", "adapter", "mode", "timeout_seconds"):
        setattr(obj, name, getattr(data, name))
    if requested_enabled:
        if data.mode != "maas" or not obj.encrypted_api_key:
            fail(
                409,
                "LLM_CONFIGURATION_INCOMPLETE",
                "启用实际调用前须选择MaaS模式、保存凭据并测试默认模型",
            )
        choices = LLMService.selections(db)
        if not choices.get("default"):
            fail(409, "LLM_MODEL_NOT_SELECTED", "请先测试并选择默认模型")
        for key in choices.values():
            model = get(db, LLMModel, key)
            if (
                not model.enabled
                or model.verification_status != "available"
                or model.tested_revision != obj.revision
            ):
                fail(409, "LLM_MODEL_NOT_VALIDATED", "所有选用模型都须通过当前凭据的实际调用测试")
    obj.enabled = requested_enabled
    obj.updated_by = db.info["actor_id"]
    obj.updated_at = now()
    audit(db, obj, "update_llm_service", request_id, before)
    return obj


def replace_key(db, data, version, request_id):
    obj = lock(db, version, data.replace_environment)
    before = public_config(db, obj)
    validate_base_url(obj.base_url)
    key = data.api_key.get_secret_value()
    public_values = [obj.service_name, obj.base_url]
    for m in db.scalars(select(LLMModel).where(LLMModel.service_id == obj.id)):
        public_values.extend([m.model_id, m.display_name])
    if any(key in value for value in public_values):
        fail(422, "LLM_CREDENTIAL_PUBLIC_VALUE_CONFLICT", "凭据不能与已公开的配置值或模型名称重合")
    obj.encrypted_api_key = CredentialVault.encrypt(data.api_key)
    obj.credential_updated_at = now()
    changed_credentials(db, obj)
    audit(db, obj, "replace_llm_credential", request_id, before)
    return obj


def remove_key(db, version, request_id):
    # Persist a tombstone even if the only old credential existed in the environment.
    obj = lock(db, version, True)
    before = public_config(db, obj)
    obj.encrypted_api_key = None
    obj.credential_updated_at = now()
    obj.enabled = False
    changed_credentials(db, obj)
    audit(db, obj, "remove_llm_credential", request_id, before)
    return obj


def models(db, obj):
    return (
        list(
            db.scalars(
                select(LLMModel)
                .where(
                    LLMModel.service_id == obj.id,
                    LLMModel.endpoint_revision == obj.endpoint_revision,
                )
                .order_by(LLMModel.model_id)
            )
        )
        if obj
        else []
    )


def public_model(model, config):
    return {
        **record(model),
        "selectable": model.enabled
        and model.verification_status == "available"
        and model.tested_revision == config.revision,
    }


def model_scope(db, obj, key):
    model = get(db, LLMModel, key, True)
    if model.service_id != obj.id or model.endpoint_revision != obj.endpoint_revision:
        fail(404, "LLM_MODEL_NOT_FOUND", "模型不属于当前生效服务地址")
    return model


def result_error(exc, revision):
    return {
        "ok": False,
        "code": exc.code,
        "message": exc.message,
        "http_status": exc.http_status,
        "service_status": exc.service_status,
        "authentication_status": exc.auth_status,
        "model_list_status": exc.list_status,
        "model_call_status": "not_tested",
        "tested_at": now().isoformat(),
        "revision": revision,
    }


def test_connection(db, obj, request_id, refresh=False):
    try:
        values, invalid = LLMService.adapter(obj).models()
        result = {
            "ok": True,
            "code": "LLM_MODELS_EMPTY" if not values else "LLM_MODELS_READ",
            "message": "模型列表为空；未证明任何模型可推理调用"
            if not values
            else "成功读取模型列表；模型调用仍须单独测试",
            "service_status": "reachable",
            "authentication_status": "accepted_for_models_endpoint",
            "model_list_status": "empty" if not values else "available",
            "model_call_status": "not_tested",
            "http_status": 200,
            "tested_at": now().isoformat(),
            "revision": obj.revision,
            "model_count": len(values),
            "invalid_entry_count": invalid,
        }
        if refresh:
            existing = {m.model_id: m for m in models(db, obj)}
            for value in values:
                model = existing.get(value["model_id"])
                if not model:
                    model = LLMModel(
                        service_id=obj.id,
                        endpoint_revision=obj.endpoint_revision,
                        source="discovered",
                        **value,
                    )
                    db.add(model)
                elif model.source == "discovered":
                    model.display_name = value["display_name"]
                model.last_discovered_at = now()
            # Missing entries are retained: listing changes are not proof of inference failure.
    except HTTPException as exc:
        result = result_error(
            ProviderError(exc.detail["code"], exc.detail["message"]), obj.revision
        )
    except ProviderError as exc:
        result = result_error(exc, obj.revision)
    if refresh:
        obj.last_models_refresh = result
    else:
        obj.last_connection_test = result
    audit(
        db,
        obj,
        "refresh_llm_models" if refresh else "test_llm_connection",
        request_id,
        extra={"test_result": result},
    )
    LLMService.log(
        db,
        "admin",
        "models_refresh" if refresh else "connection_test",
        "database",
        obj.revision,
        None,
        result["code"],
        result.get("http_status"),
    )
    return result


def add_model(db, obj, data, request_id):
    if obj.encrypted_api_key:
        secret = CredentialVault.decrypt(obj.encrypted_api_key).get_secret_value()
        if secret in data.model_id or secret in (data.display_name or ""):
            fail(422, "LLM_MODEL_INVALID", "模型字段不能包含服务凭据")
    model = LLMModel(
        service_id=obj.id,
        endpoint_revision=obj.endpoint_revision,
        model_id=data.model_id,
        display_name=data.display_name or data.model_id,
        source="manual",
    )
    db.add(model)
    audit(db, model, "add_llm_model", request_id)
    return model


def used_by(db, model):
    return list(
        db.scalars(select(LLMSelection.scenario).where(LLMSelection.model_config_id == model.id))
    )


def mutate_model(db, model, version, request_id, enabled=None, delete=False):
    match(model, version)
    if (delete or enabled is False) and used_by(db, model):
        fail(409, "LLM_MODEL_IN_USE", "模型正被默认或业务场景引用，请先改选或取消引用")
    if delete and model.source != "manual":
        fail(
            409, "LLM_DISCOVERED_MODEL_DELETE_FORBIDDEN", "接口发现的模型可禁用；仅手动模型允许删除"
        )
    before = record(model)
    if delete:
        audit(db, model, "delete_llm_model", request_id, before)
        db.delete(model)
    else:
        model.enabled = enabled
        audit(db, model, "update_llm_model", request_id, before)


def choose(db, obj, scenario, key, request_id):
    old = db.scalar(
        select(LLMSelection).where(
            LLMSelection.service_id == obj.id, LLMSelection.scenario == scenario
        )
    )
    before = public_config(db, obj)
    if key:
        model = model_scope(db, obj, key)
        if (
            not model.enabled
            or model.verification_status != "available"
            or model.tested_revision != obj.revision
        ):
            fail(409, "LLM_MODEL_NOT_VALIDATED", "先启用并测试该模型，通过后才可选用")
        if old:
            old.model_config_id = key
        else:
            db.add(LLMSelection(service_id=obj.id, scenario=scenario, model_config_id=key))
    elif old:
        db.delete(old)
    if scenario == "default" and not key:
        obj.enabled = False
    obj.updated_by = db.info["actor_id"]
    obj.updated_at = now()
    audit(db, obj, "select_llm_model", request_id, before, {"scenario": scenario})
    return obj


def test_model(db, obj, model, request_id):
    if not model.enabled:
        fail(409, "LLM_MODEL_DISABLED", "请先启用该模型")
    try:
        LLMService.adapter(obj).chat(
            model.model_id, [{"role": "user", "content": "Reply OK."}], test=True
        )
        result = {
            "ok": True,
            "code": "LLM_MODEL_AVAILABLE",
            "message": "选定模型已通过最小Chat Completions调用测试；结构化输出能力还需业务调用验证",
            "service_status": "reachable",
            "authentication_status": "accepted_for_chat_endpoint",
            "model_list_status": "not_tested",
            "model_call_status": "available",
            "http_status": 200,
            "tested_at": now().isoformat(),
            "revision": obj.revision,
        }
        model.verification_status = "available"
    except HTTPException as exc:
        result = result_error(
            ProviderError(exc.detail["code"], exc.detail["message"]), obj.revision
        )
        model.verification_status = "untested"
    except ProviderError as exc:
        result = result_error(exc, obj.revision)
        model.verification_status = "untested" if exc.http_status in (200, 404) else "failed"
    if not result["ok"]:
        result["model_call_status"] = (
            "incomplete"
            if result["code"] == "LLM_TEST_OUTPUT_TRUNCATED"
            else "unsupported_or_unverified"
            if result.get("http_status") in (200, 404)
            else "failed"
        )
    model.last_tested_at = now()
    model.tested_revision = obj.revision
    model.last_test_result = result
    audit(db, model, "test_llm_model", request_id, extra={"test_result": result})
    LLMService.log(
        db,
        "admin",
        "model_test",
        "database",
        obj.revision,
        model.model_id,
        result["code"],
        result.get("http_status"),
    )
    return result


def import_environment(db, version, request_id):
    if db.get(LLMConfig, SERVICE_ID):
        fail(409, "LLM_ADMIN_CONFIG_EXISTS", "管理员配置已存在，拒绝被旧环境覆盖")
    base = validate_base_url(settings.ai_base_url or DEFAULT_BASE_URL)
    obj = lock(db, version, True)
    obj.base_url = base
    obj.mode = "mock"
    obj.enabled = False
    if settings.ai_api_key.get_secret_value():
        obj.encrypted_api_key = CredentialVault.encrypt(settings.ai_api_key)
        obj.credential_updated_at = now()
    if settings.ai_model:
        db.add(
            LLMModel(
                service_id=obj.id,
                endpoint_revision=obj.endpoint_revision,
                model_id=settings.ai_model,
                display_name=settings.ai_model,
                source="manual",
            )
        )
    audit(db, obj, "import_llm_environment", request_id)
    return obj
