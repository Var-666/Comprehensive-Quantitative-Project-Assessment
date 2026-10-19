from fastapi import Request, Response
from sqlalchemy import select

from . import auth
from . import services as svc
from .config import settings
from .models import AuthSession, Credential, Project, ProjectMember, User
from .schemas import LoginInput, MemberInput


def register(app, Db, ok):
    @app.post("/api/v1/auth/login")
    def login(request: Request, response: Response, data: LoginInput, db: Db):
        origin = request.headers.get("origin")
        if origin and origin not in settings.allowed_origins.split(","):
            svc.fail(403, "ORIGIN_REJECTED", "登录来源未配置")
        account, session, token = auth.login(db, data.username, data.password)
        db.commit()
        response.set_cookie(
            "project_session",
            token,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="strict",
            max_age=settings.session_hours * 3600,
            path="/",
        )
        user = db.get(User, account.user_id)
        return ok(
            request,
            {
                "user_id": user.id,
                "display_name": user.display_name,
                "username": account.username,
                "is_system_admin": account.is_system_admin,
                "csrf_token": session.csrf_token,
            },
        )

    @app.get("/api/v1/auth/me")
    def me(request: Request, db: Db):
        principal = request.state.principal
        members = db.scalars(
            select(ProjectMember).where(
                ProjectMember.user_id == principal.user_id, ProjectMember.active.is_(True)
            )
        ).all()
        return ok(
            request,
            {
                **vars(principal),
                "memberships": [svc.record(m) for m in members],
                "demo_mode": settings.demo_mode,
            },
        )

    @app.post("/api/v1/auth/logout")
    def logout(request: Request, response: Response, db: Db):
        session = db.get(AuthSession, request.state.principal.session_id)
        db.delete(session)
        db.commit()
        response.delete_cookie("project_session", path="/")
        return ok(request, {"logged_out": True})

    @app.get("/api/v1/projects/{project_id}/members")
    def members(request: Request, project_id: str, db: Db):
        values = []
        for member in db.scalars(
            select(ProjectMember).where(ProjectMember.project_id == project_id)
        ):
            values.append(
                {**svc.record(member), "display_name": db.get(User, member.user_id).display_name}
            )
        return ok(request, values)

    @app.put("/api/v1/projects/{project_id}/members")
    def set_member(request: Request, project_id: str, data: MemberInput, db: Db):
        svc.get(db, Project, project_id)
        # Only real provisioned accounts can be granted privileges, not arbitrary directory entries.
        if not db.scalar(
            select(Credential.id).where(
                Credential.user_id == data.user_id, Credential.enabled.is_(True)
            )
        ):
            svc.fail(422, "ACCOUNT_REQUIRED", "请先为该人员配置可用登录账号")
        if (
            data.user_id == request.state.principal.user_id
            and not request.state.principal.is_system_admin
        ):
            svc.fail(403, "SELF_PERMISSION_CHANGE", "项目管理员不能自行变更自己的授权")
        member = db.scalar(
            select(ProjectMember)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == data.user_id,
                ProjectMember.role_code == data.role_code,
            )
            .with_for_update()
        )
        before = svc.record(member) if member else None
        if not member:
            member = ProjectMember(project_id=project_id, **data.model_dump())
            db.add(member)
        else:
            member.active = data.active
        svc.audit(
            db,
            member,
            "grant_role" if data.active else "revoke_role",
            request.state.request_id,
            before,
        )
        db.commit()
        return ok(request, svc.record(member))
