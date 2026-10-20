from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator

from .schemas import Input

ModelID = Annotated[str, Field(min_length=1, max_length=256)]


class ServiceInput(Input):
    service_name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=500)
    adapter: Literal["openai_compatible"] = "openai_compatible"
    mode: Literal["mock", "maas"] = "mock"
    enabled: bool = False
    timeout_seconds: int = Field(default=20, ge=1, le=60)
    replace_environment: bool = False


class CredentialInput(Input):
    api_key: SecretStr = Field(min_length=1, max_length=8192)
    replace_environment: bool = False

    @field_validator("api_key")
    @classmethod
    def safe_key(cls, value):
        text = value.get_secret_value()
        if text != text.strip() or any(ord(c) < 33 or ord(c) > 126 for c in text):
            raise ValueError("密钥不能包含空白、换行或非ASCII字符")
        return value


class ManualModelInput(Input):
    model_id: ModelID
    display_name: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("model_id", "display_name")
    @classmethod
    def printable(cls, value):
        if value and any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("模型ID和名称不能包含控制字符")
        return value


class ModelUpdate(Input):
    enabled: bool


class ModelChoice(Input):
    model_config_id: str | None = None


class ScenarioChoices(Input):
    analysis: str | None = None
    notification: str | None = None


class EnvironmentImport(Input):
    confirmed: Literal[True]
