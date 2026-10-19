import os
import secrets
from contextlib import contextmanager

os.environ["APP_ENV"] = "test"
os.environ["DEMO_MODE"] = "true"
os.environ["COOKIE_SECURE"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import update  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.auth import passwords  # noqa: E402
from app.db import Base, get_db, make_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Credential, Department, NodeType, Project, User  # noqa: E402

TEST_PASSWORD = secrets.token_urlsafe(24)
PASSWORD_HASH = passwords.hash(TEST_PASSWORD)
REVIEWER_ID = "00000000-0000-0000-0000-000000000003"
VIEWER_ID = "00000000-0000-0000-0000-000000000004"


def login_as(client, username="admin"):
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["data"]["csrf_token"]


@contextmanager
def as_reviewer(client):
    login_as(client, "reviewer")
    try:
        yield
    finally:
        login_as(client)


@pytest.fixture
def factory(tmp_path):
    # PostgreSQL verification may supply a dedicated disposable test database.
    url = os.getenv("TEST_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add(
            Department(id="00000000-0000-0000-0000-000000000001", dept_code="D", dept_name="项目部")
        )
        db.add(
            User(id="00000000-0000-0000-0000-000000000002", employee_code="U", display_name="张工")
        )
        db.add(NodeType(code="设计资料", display_name="设计资料"))
        db.add(User(id=REVIEWER_ID, employee_code="REVIEWER", display_name="审核人员"))
        db.add(User(id=VIEWER_ID, employee_code="VIEWER", display_name="只读人员"))
        db.flush()
        for username, user_id, admin in (
            ("admin", "00000000-0000-0000-0000-000000000002", True),
            ("reviewer", REVIEWER_ID, False),
            ("viewer", VIEWER_ID, False),
        ):
            db.add(
                Credential(
                    user_id=user_id,
                    username=username,
                    password_hash=PASSWORD_HASH,
                    is_system_admin=admin,
                )
            )
    yield factory
    # Break the intentional project <-> current plan cycle before fixture teardown.
    with factory.begin() as db:
        db.execute(update(Project).values(current_plan_version_id=None))
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(factory):
    def override():
        with factory() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        login_as(client)
        yield client
    app.dependency_overrides.clear()
