"""Database sessions and project roles. Password hashing is delegated to pwdlib/Argon2."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta, timezone

from fastapi import Depends, Request
from fastapi.security import APIKeyCookie
from pwdlib import PasswordHash
from sqlalchemy import select

from .config import settings
from .db import get_db
from .models import (
    ActualRecord,
    AuthSession,
    Credential,
    ImportBatch,
    Milestone,
    PlanVersion,
    ProjectMember,
    User,
    now,
)
from .services import fail

passwords = PasswordHash.recommended()
dummy_hash = passwords.hash(secrets.token_urlsafe(24))
cookie = APIKeyCookie(name="project_session", auto_error=False)
ROLES = {
    "read": {"admin", "editor", "reviewer", "viewer"},
    "write": {"admin", "editor"},
    "review": {"admin", "reviewer"},
    "manage": {"admin"},
}


@dataclass
class Principal:
    user_id: str
    username: str
    display_name: str
    is_system_admin: bool
    session_id: str
    csrf_token: str


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(request: Request, token=Depends(cookie), db=Depends(get_db)):
    if not token:
        fail(401, "UNAUTHENTICATED", "请先登录")
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token)))
    if session is None or utc(session.expires_at) <= now():
        fail(401, "SESSION_EXPIRED", "登录已过期，请重新登录")
    account = db.get(Credential, session.credential_id)
    if not account or not account.enabled:
        fail(401, "ACCOUNT_DISABLED", "账号不可用")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), session.csrf_token):
            fail(403, "CSRF_INVALID", "请求校验失败，请刷新页面")
    user = db.get(User, account.user_id)
    principal = Principal(
        user.id,
        account.username,
        user.display_name,
        account.is_system_admin,
        session.id,
        session.csrf_token,
    )
    request.state.principal = principal
    db.info["principal"] = principal
    db.info["actor_id"] = principal.user_id
    return principal


def authorize(request: Request, token=Depends(cookie), db=Depends(get_db)):
    if request.url.path in ("/api/v1/health", "/api/v1/auth/login"):
        return
    principal = authenticate(request, token, db)
    path = request.url.path
    if path.startswith("/api/v1/auth/"):
        return
    action = "read" if request.method in ("GET", "HEAD") else "write"
    if path.endswith(("/activate", "/verify")):
        action = "review"
    if "/members" in path or "/financial-access" in path:
        action = "manage" if request.method != "GET" else "read"
    params = request.path_params
    project_id = params.get("project_id")
    for key, model in (
        ("milestone_id", Milestone),
        ("version_id", PlanVersion),
        ("actual_id", ActualRecord),
        ("batch_id", ImportBatch),
    ):
        if key not in params:
            continue
        from .services import get

        obj = get(db, model, params[key])
        if model is ActualRecord:
            project_id = get(db, Milestone, obj.milestone_id).project_id
        elif model is ImportBatch:
            if obj.created_by != principal.user_id and not principal.is_system_admin:
                fail(404, "IMPORT_NOT_FOUND", "导入批次不存在或未授权")
            project_id = obj.context_json.get("project_id")
            if not project_id and not principal.is_system_admin:
                fail(403, "FORBIDDEN", "仅系统管理员可导入项目")
        else:
            project_id = obj.project_id
    if project_id:
        # System operators may allocate project roles without obtaining business read/write access.
        if action == "manage" and principal.is_system_admin:
            return
        require_project(db, principal, project_id, action)
    elif path == "/api/v1/projects" and request.method == "POST" and not principal.is_system_admin:
        fail(403, "FORBIDDEN", "仅系统管理员可创建项目")


def role(db, principal, project_id):
    return set(
        db.scalars(
            select(ProjectMember.role_code).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == principal.user_id,
                ProjectMember.active.is_(True),
            )
        )
    )


def require_project(db, principal, project_id, action="read"):
    roles = role(db, principal, project_id)
    if not roles:
        fail(404, "PROJECT_NOT_FOUND", "项目不存在或未授权")
    if not roles & ROLES[action]:
        fail(403, "FORBIDDEN", "当前项目角色无权执行此操作")


def visible_projects(principal):
    return select(ProjectMember.project_id).where(
        ProjectMember.user_id == principal.user_id, ProjectMember.active.is_(True)
    )


def login(db, username, password):
    account = db.scalar(select(Credential).where(Credential.username == username).with_for_update())
    if account and account.locked_until and utc(account.locked_until) > now():
        fail(429, "LOGIN_LOCKED", "登录失败次数过多，请稍后重试")
    valid = passwords.verify(password, account.password_hash if account else dummy_hash)
    if not account or not valid or not account.enabled:
        if account:
            account.failed_attempts += 1
            if account.failed_attempts >= 5:
                account.locked_until = now() + timedelta(minutes=15)
            db.commit()
        fail(401, "INVALID_CREDENTIALS", "账号或密码错误")
    account.failed_attempts = 0
    account.locked_until = None
    token = secrets.token_urlsafe(48)
    session = AuthSession(
        credential_id=account.id,
        token_hash=token_hash(token),
        csrf_token=secrets.token_urlsafe(32),
        expires_at=now() + timedelta(hours=settings.session_hours),
    )
    db.add(session)
    db.flush()
    return account, session, token
