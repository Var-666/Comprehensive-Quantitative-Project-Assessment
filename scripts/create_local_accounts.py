"""Create local sample accounts once; secrets stay in an ignored, owner-only file."""

import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from sqlalchemy import select  # noqa: E402

from app.admin import provision  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Project, ProjectMember  # noqa: E402
from app.seed import load_sample  # noqa: E402
from app.services import audit  # noqa: E402

target = ROOT / ".local-access.json"
if target.exists():
    print("本机账号文件已存在，不重置账号或密码：.local-access.json")
    sys.exit(0)
if settings.app_env not in ("development", "test") or not settings.demo_mode:
    raise RuntimeError("仅允许在本地模拟环境创建样本账号")
credentials = []
with SessionLocal.begin() as db:
    load_sample(db, ROOT / "模拟业务测试数据 V0.1.xlsx")
    db.info["actor_id"] = "operator-cli"
    for username, display_name, role, admin in (
        ("local-editor", "本机编制人员", "admin", True),
        ("local-reviewer", "本机审核人员", "reviewer", False),
        ("local-viewer", "本机只读人员", "viewer", False),
    ):
        password = secrets.token_urlsafe(24)
        account = provision(db, username, display_name, password, admin)
        for project in db.scalars(select(Project).where(Project.data_source == "sample_excel")):
            member = ProjectMember(project_id=project.id, user_id=account.user_id, role_code=role)
            db.add(member)
            audit(db, member, "initial_sample_grant", "local-provision")
        credentials.append(
            {"username": username, "password": password, "display_name": display_name}
        )
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(json.dumps(credentials, ensure_ascii=False, indent=2) + "\n")
    except Exception:
        target.unlink(missing_ok=True)
        raise
print("三个独立本机账号已创建。凭据保存在 .local-access.json（权限0600，已忽略Git）")
