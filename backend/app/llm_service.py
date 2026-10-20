"""All business model calls resolve a fresh configuration; credentials remain private here."""

import logging
from dataclasses import dataclass

from pydantic import SecretStr, ValidationError
from sqlalchemy import select

from .config import settings
from .llm_models import SERVICE_ID, LLMCallLog, LLMConfig, LLMModel, LLMSelection
from .llm_provider import OpenAICompatibleAdapter, ProviderError
from .llm_schemas import CredentialInput, ManualModelInput
from .llm_secrets import CredentialVault
from .services import fail

logger = logging.getLogger("llm-service")


@dataclass(frozen=True)
class RuntimeConfig:
    provider: str
    source: str
    base_url: str = ""
    api_key: SecretStr = SecretStr("")
    model_id: str | None = None
    timeout: float = 20
    external_enabled: bool = False
    revision: int | None = None


class LLMService:
    @staticmethod
    def legacy_values():
        try:
            key = (
                CredentialInput(api_key=settings.ai_api_key).api_key
                if settings.ai_api_key.get_secret_value()
                else SecretStr("")
            )
            model = (
                ManualModelInput(model_id=settings.ai_model).model_id if settings.ai_model else None
            )
        except ValidationError:
            fail(422, "LLM_ENVIRONMENT_INVALID", "旧环境模型或凭据格式无效，请通过系统设置重新配置")
        secret = key.get_secret_value()
        if secret and (secret in settings.ai_base_url or secret in (model or "")):
            fail(
                422,
                "LLM_CREDENTIAL_PUBLIC_VALUE_CONFLICT",
                "旧环境地址或模型字段含凭据，已拒绝公开或迁移",
            )
        return key, model

    @staticmethod
    def legacy_configured():
        return bool(
            settings.ai_base_url
            or settings.ai_model
            or settings.ai_api_key.get_secret_value()
            or settings.ai_provider != "mock"
        )

    @staticmethod
    def selections(db):
        return {
            o.scenario: o.model_config_id
            for o in db.scalars(select(LLMSelection).where(LLMSelection.service_id == SERVICE_ID))
        }

    @classmethod
    def runtime(cls, db=None, scenario="analysis"):
        config = db.get(LLMConfig, SERVICE_ID) if db is not None else None
        if config is not None:
            if config.mode == "mock":
                return RuntimeConfig("mock", "database", revision=config.revision)
            if not config.enabled:
                fail(409, "LLM_DISABLED", "管理员尚未启用实际模型调用")
            choices = cls.selections(db)
            model = (
                db.get(LLMModel, choices.get(scenario) or choices.get("default"))
                if (choices.get(scenario) or choices.get("default"))
                else None
            )
            if (
                not model
                or not model.enabled
                or model.endpoint_revision != config.endpoint_revision
            ):
                fail(409, "LLM_MODEL_NOT_SELECTED", "当前场景没有可用的已保存模型配置")
            if model.verification_status != "available" or model.tested_revision != config.revision:
                fail(
                    409,
                    "LLM_MODEL_NOT_VALIDATED",
                    "模型尚未通过当前地址与凭据的调用测试，请管理员重新测试",
                )
            return RuntimeConfig(
                "openai_compatible",
                "database",
                config.base_url,
                CredentialVault.decrypt(config.encrypted_api_key),
                model.model_id,
                config.timeout_seconds,
                True,
                config.revision,
            )
        if settings.ai_provider == "mock":
            return RuntimeConfig("mock", "environment")
        if not settings.ai_external_enabled:
            fail(
                409,
                "EXTERNAL_AI_NOT_AUTHORIZED",
                "旧环境模式尚未允许外送；请显式迁移为管理员配置或由运维批准",
            )
        if (
            not settings.ai_base_url
            or not settings.ai_model
            or not settings.ai_api_key.get_secret_value()
        ):
            fail(
                503,
                "MODEL_NOT_CONFIGURED",
                "请配置服务地址、模型和凭据，或由管理员在系统设置迁移旧环境配置",
            )
        key, model = cls.legacy_values()
        return RuntimeConfig(
            "openai_compatible",
            "environment",
            settings.ai_base_url,
            key,
            model,
            settings.ai_timeout_seconds,
            settings.ai_external_enabled,
        )

    @staticmethod
    def adapter(config):
        return OpenAICompatibleAdapter(
            config.base_url,
            CredentialVault.decrypt(config.encrypted_api_key),
            config.timeout_seconds,
        )

    @staticmethod
    def log(db, scenario, operation, source, revision, model_id, code, http_status=None):
        # Neither prompts, generated text, URLs, credentials nor provider exception text are logged.
        logger.info(
            "operation=%s scenario=%s source=%s revision=%s outcome=%s http_status=%s",
            operation,
            scenario,
            source,
            revision,
            code,
            http_status,
        )
        if db is not None:
            db.add(
                LLMCallLog(
                    scenario=scenario,
                    operation=operation,
                    configuration_source=source,
                    revision=revision,
                    model_id=model_id,
                    outcome_code=code,
                    http_status=http_status,
                    actor_id=db.info.get("actor_id", "system"),
                )
            )

    @classmethod
    def chat(cls, runtime, messages, response_format, db=None, scenario="analysis", factory=None):
        try:
            result = OpenAICompatibleAdapter(
                runtime.base_url, runtime.api_key, runtime.timeout, factory
            ).chat(runtime.model_id, messages, response_format)
            cls.log(
                db,
                scenario,
                "chat",
                runtime.source,
                runtime.revision,
                runtime.model_id,
                "LLM_CALL_SUCCEEDED",
                200,
            )
            return result
        except ProviderError as exc:
            cls.log(
                db,
                scenario,
                "chat",
                runtime.source,
                runtime.revision,
                runtime.model_id,
                exc.code,
                exc.http_status,
            )
            fail(
                503
                if exc.http_status in (401, 403, 429) or exc.http_status and exc.http_status >= 500
                else 502,
                exc.code,
                exc.message,
            )

    @classmethod
    def describe(cls, db):
        config = db.get(LLMConfig, SERVICE_ID)
        if config:
            mock = config.mode == "mock"
            choices = cls.selections(db)
            return {
                "provider": "mock" if mock else "openai_compatible",
                "external_enabled": config.enabled and not mock,
                "configured": mock
                or bool(config.encrypted_api_key and config.enabled and choices.get("default")),
                "mode_label": "Mock · 无真实模型连接" if mock else "MaaS · 按管理员生效配置调用",
                "configuration_source": "database",
            }
        return {
            "provider": settings.ai_provider,
            "external_enabled": settings.ai_external_enabled,
            "configured": settings.ai_provider == "mock"
            or bool(
                settings.ai_base_url
                and settings.ai_model
                and settings.ai_api_key.get_secret_value()
            ),
            "mode_label": "Mock · 无真实模型连接"
            if settings.ai_provider == "mock"
            else "真实模型辅助事实分类整理",
            "configuration_source": "environment",
        }
