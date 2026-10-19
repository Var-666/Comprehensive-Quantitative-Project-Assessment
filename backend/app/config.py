from pathlib import Path

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
    allowed_origins: str = "http://127.0.0.1:5173,http://127.0.0.1:5174,http://localhost:5173,http://127.0.0.1:8000,http://127.0.0.1:8001,http://127.0.0.1:8011"


settings = Settings()

PENDING_RULES = {
    "D-02": "2026-10-20已确认：项目编号全局唯一，节点编号项目内唯一；不限制未提供的编号格式",
    "D-03": "2026-10-20已确认：按项目授权，计划编制人与批准人分离",
    "D-08": "2026-10-20已确认：Excel遇错整批回滚、重复编号不覆盖",
    "D-09": "评价口径待确认；第一阶段不出绩效指标",
    "D-11/D-12": "2026-10-20已确认：admin/editor/reviewer/viewer项目角色；实际提交人与核实人分离",
    "D-15": "证据存储待确认；当前保留来源说明，不冒充正式附件",
}
