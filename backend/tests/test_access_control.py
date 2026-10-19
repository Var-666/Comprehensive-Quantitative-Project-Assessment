from datetime import timedelta

from sqlalchemy import select

from app.models import AuditEvent, AuthSession, Credential
from conftest import REVIEWER_ID, TEST_PASSWORD, VIEWER_ID, as_reviewer, login_as
from test_phase1 import create, node_payload, preview


def grant(client, project_id, user_id=VIEWER_ID, role="viewer", active=True):
    response = client.put(
        f"/api/v1/projects/{project_id}/members",
        json={"user_id": user_id, "role_code": role, "active": active},
    )
    assert response.status_code == 200, response.text


def test_all_business_routes_require_login(client):
    client.cookies.clear()
    for path in (
        "/projects",
        "/summary",
        "/users",
        "/departments",
        "/config",
        "/dictionaries/node-types",
    ):
        response = client.get("/api/v1" + path)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert client.get("/api/v1/health").status_code == 200


def test_scopes_apply_to_lists_stats_nodes_versions_and_imports(client):
    """An authenticated outsider cannot enumerate a project through any subordinate resource."""
    p, plan = create(client)
    node = client.post(
        f"/api/v1/projects/{p['id']}/milestones", json=node_payload(plan["id"])
    ).json()["data"]
    batch = preview(client, [["P-UPLOAD", "only author"]]).json()["data"]
    login_as(client, "viewer")
    assert client.get("/api/v1/projects").json()["data"]["total"] == 0
    assert client.get("/api/v1/summary").json()["data"]["milestones"] == 0
    for path in (
        f"/projects/{p['id']}",
        f"/projects/{p['id']}/milestones",
        f"/projects/{p['id']}/audit-events",
        f"/milestones/{node['id']}",
        f"/imports/{batch['id']}",
        f"/imports/{batch['id']}/errors",
    ):
        assert client.get("/api/v1" + path).status_code == 404
    assert (
        client.post(
            f"/api/v1/plan-versions/{plan['id']}/activate",
            headers={"If-Match": "1"},
            json={"approval_ref": "unauthorized"},
        ).status_code
        == 404
    )


def test_viewer_cannot_write_and_revocation_takes_effect_in_existing_session(client):
    p, plan = create(client)
    grant(client, p["id"])
    login_as(client, "viewer")
    assert client.get(f"/api/v1/projects/{p['id']}").status_code == 200
    assert (
        client.post(
            f"/api/v1/projects/{p['id']}/milestones", json=node_payload(plan["id"])
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/projects", json={"project_code": "NO", "project_name": "NO"}
        ).status_code
        == 403
    )
    viewer_cookie = client.cookies.get("project_session")
    viewer_csrf = client.headers["X-CSRF-Token"]
    login_as(client)
    grant(client, p["id"], active=False)
    client.cookies.clear()
    client.cookies.set("project_session", viewer_cookie)
    client.headers["X-CSRF-Token"] = viewer_csrf
    assert client.get(f"/api/v1/projects/{p['id']}").status_code == 404


def test_contributors_cannot_self_approve_and_reviewer_cannot_edit(client):
    p, plan = create(client)
    n = client.post(f"/api/v1/projects/{p['id']}/milestones", json=node_payload(plan["id"])).json()[
        "data"
    ]
    version = client.get(f"/api/v1/projects/{p['id']}/plan-versions").json()["data"][0]
    response = client.post(
        f"/api/v1/plan-versions/{plan['id']}/activate",
        headers={"If-Match": str(version["row_version"])},
        json={"approval_ref": "self"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SELF_APPROVAL_FORBIDDEN"
    with as_reviewer(client):
        assert (
            client.patch(
                f"/api/v1/milestones/{n['id']}/plan-item",
                headers={"If-Match": "1"},
                json=node_payload(plan["id"]),
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/v1/plan-versions/{plan['id']}/activate",
                headers={"If-Match": str(version["row_version"])},
                json={"approval_ref": "independent"},
            ).status_code
            == 200
        )


def test_submission_review_and_audit_actor_are_independent(client, factory):
    p, plan = create(client)
    node = client.post(
        f"/api/v1/projects/{p['id']}/milestones", json=node_payload(plan["id"])
    ).json()["data"]
    actual = client.post(
        f"/api/v1/milestones/{node['id']}/actuals",
        headers={"X-Actor-ID": REVIEWER_ID},
        json={
            "actual_date": "2026-10-01",
            "completion_flag": True,
            "evidence_ref": "evidence source",
        },
    ).json()["data"]
    assert actual["submitted_by"] != REVIEWER_ID
    response = client.post(
        f"/api/v1/milestone-actuals/{actual['id']}/verify",
        json={"decision": "verified", "comment": "self"},
    )
    assert (
        response.status_code == 403
        and response.json()["error"]["code"] == "SELF_VERIFICATION_FORBIDDEN"
    )
    with as_reviewer(client):
        verified = client.post(
            f"/api/v1/milestone-actuals/{actual['id']}/verify",
            json={"decision": "verified", "comment": "independent"},
        ).json()["data"]
        assert verified["verified_by"] == REVIEWER_ID
    with factory() as db:
        event = db.scalar(
            select(AuditEvent).where(
                AuditEvent.aggregate_id == actual["id"], AuditEvent.action == "verify"
            )
        )
        assert event.actor_id == REVIEWER_ID


def test_csrf_logout_expiration_and_disabled_account(client, factory):
    client.headers["X-CSRF-Token"] = "wrong"
    assert client.post("/api/v1/auth/logout").status_code == 403
    login_as(client)
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
    login_as(client)
    with factory.begin() as db:
        for session in db.scalars(select(AuthSession)):
            session.expires_at = session.expires_at - timedelta(days=1)
    assert client.get("/api/v1/auth/me").status_code == 401
    login_as(client)
    with factory.begin() as db:
        db.scalar(select(Credential).where(Credential.username == "admin")).enabled = False
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_throttle_and_foreign_origin(client):
    assert (
        client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://other.example"},
            json={"username": "viewer", "password": TEST_PASSWORD},
        ).status_code
        == 403
    )
    for _ in range(5):
        assert (
            client.post(
                "/api/v1/auth/login", json={"username": "viewer", "password": "incorrect"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "viewer", "password": TEST_PASSWORD}
        ).status_code
        == 429
    )
