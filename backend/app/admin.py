"""Local operator CLI. No default passwords or network registration endpoint."""

import argparse
import getpass
import os

from sqlalchemy import select

from .auth import passwords
from .db import SessionLocal
from .models import AuditEvent, Credential, Project, ProjectMember, User


def provision(db, username, display_name, password, admin=False):
    if not 12 <= len(password) <= 200:
        raise ValueError("密码长度必须为12至200个字符")
    if db.scalar(select(Credential.id).where(Credential.username == username)):
        raise ValueError("账号已存在；不会覆盖密码或权限")
    user = User(employee_code=f"LOCAL-{username}", display_name=display_name)
    db.add(user)
    db.flush()
    account = Credential(
        user_id=user.id,
        username=username,
        password_hash=passwords.hash(password),
        is_system_admin=admin,
    )
    db.add(account)
    db.flush()
    db.add(
        AuditEvent(
            aggregate_type="auth_credentials",
            aggregate_id=account.id,
            action="provision_account",
            after_json={"user_id": user.id, "username": username, "is_system_admin": admin},
            actor_id="operator-cli",
            request_id="local-provision",
        )
    )
    return account


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("--name", required=True)
    parser.add_argument("--system-admin", action="store_true")
    parser.add_argument("--grant-samples", choices=["admin", "editor", "reviewer", "viewer"])
    args = parser.parse_args()
    password = os.getenv("INITIAL_USER_PASSWORD") or getpass.getpass("初始密码（至少12字符）：")
    with SessionLocal.begin() as db:
        account = db.scalar(select(Credential).where(Credential.username == args.username))
        if not account:
            account = provision(db, args.username, args.name, password, args.system_admin)
        elif not args.grant_samples:
            raise ValueError("账号已存在；不会覆盖密码或权限")
        if args.grant_samples:
            for project in db.scalars(select(Project).where(Project.data_source == "sample_excel")):
                if not db.scalar(
                    select(ProjectMember.id).where(
                        ProjectMember.project_id == project.id,
                        ProjectMember.user_id == account.user_id,
                        ProjectMember.role_code == args.grant_samples,
                    )
                ):
                    db.add(
                        ProjectMember(
                            project_id=project.id,
                            user_id=account.user_id,
                            role_code=args.grant_samples,
                        )
                    )
    print(f"账号已创建：{args.username}；项目角色需独立授权")
