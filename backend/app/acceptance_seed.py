"""Explicit disposable acceptance environment setup; credentials come only from the environment."""

import os

from sqlalchemy import select

from .admin import provision
from .config import ROOT, settings
from .db import SessionLocal
from .models import Project, ProjectMember
from .seed import load_sample


def initialize(db, password):
    if settings.app_env not in ("development", "test") or not settings.demo_mode:
        raise RuntimeError("验收样本仅允许在开发/测试环境初始化")
    load_sample(db, ROOT / "模拟业务测试数据 V0.1.xlsx")
    for username, name, role, system_admin in (
        ("accept-editor", "验收编制人员", "admin", True),
        ("accept-reviewer", "验收审核人员", "reviewer", False),
        ("accept-viewer", "验收只读人员", "viewer", False),
    ):
        account = provision(db, username, name, password, system_admin)
        for p in db.scalars(select(Project).where(Project.data_source == "sample_excel")):
            db.add(ProjectMember(project_id=p.id, user_id=account.user_id, role_code=role))


if __name__ == "__main__":
    with SessionLocal.begin() as db:
        initialize(db, os.environ["ACCEPTANCE_PASSWORD"])
    print("验收数据及三个独立账号已创建；密码来自环境，未输出")
