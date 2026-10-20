from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    app_env: str = "development"
    database_url: str = f"sqlite:///{ROOT / 'development.db'}"
    business_timezone: str = "Asia/Shanghai"
    max_upload_bytes: int = 5 * 1024 * 1024
    max_excel_rows: int = 2000
    # Restricts sample data; never bypasses authentication or authorization.
    demo_mode: bool = True
    session_hours: int = 8
    cookie_secure: bool = False
    ai_provider: Literal["mock", "openai_compatible"] = "mock"
    ai_base_url: str = ""
    ai_model: str = ""
    ai_api_key: SecretStr = SecretStr("")
    ai_external_enabled: bool = False
    ai_timeout_seconds: float = Field(default=20, ge=1, le=60)
    llm_encryption_key: SecretStr = SecretStr("")
    llm_encryption_key_file: str = ""
    llm_allowed_origins: str = "https://maas-api.cmhk.com"
    llm_private_origins: str = ""
    llm_allow_local_http_credentials: bool = False
    allowed_origins: str = "http://127.0.0.1:5173,http://127.0.0.1:5174,http://localhost:5173,http://127.0.0.1:8000,http://127.0.0.1:8001,http://127.0.0.1:8011"


settings = Settings()

PENDING_RULES = {
    "D-04": "模板适用条件和核实依据逐条编制、独立批准；模拟Excel内容保持草稿，不自动批准",
    "D-05": "提前天数、接收角色及追补窗口逐条批准；每计划快照/规则版本/接收人只生成一轮草稿",
    "D-06": "企业工作日历逐日显式配置并独立批准，无批准日历不计算正式工作日",
    "D-07": "2026-10-20已确认独立通知审核；站内发布需另行操作，外部通知渠道关闭",
    "D-02": "2026-10-20已确认：项目编号全局唯一，节点编号项目内唯一；不限制未提供的编号格式",
    "D-03": "2026-10-20已确认：按项目授权，计划编制人与批准人分离",
    "D-08": "2026-10-20已确认：Excel遇错整批回滚、重复编号不覆盖",
    "D-09": "2026-10-20已确认试算O/(O+L)，待核对、已核实逾期未完成单列；不生成综合得分",
    "D-11/D-12": "2026-10-20已确认：admin/editor/reviewer/viewer项目角色；实际提交人与核实人分离",
    "D-15": "证据存储待确认；当前保留来源说明，不冒充正式附件",
}
