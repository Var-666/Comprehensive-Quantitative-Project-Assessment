import os
import subprocess
import sys

from sqlalchemy import inspect

from app.db import make_engine


def alembic(*args, url):
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=True,
    )


def test_migration_roundtrip_and_postgres_ddl(tmp_path):
    """Installable schemas must retain the current-plan FK, including PostgreSQL's cycle."""
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    alembic("upgrade", "head", url=url)
    engine = make_engine(url)
    schema = inspect(engine)
    assert "projects" in schema.get_table_names()
    checks = schema.get_check_constraints("milestone_actual_records")
    assert len(checks) == 3
    assert any(
        fk["referred_table"] == "project_plan_versions"
        for fk in schema.get_foreign_keys("projects")
    )
    engine.dispose()
    alembic("downgrade", "base", url=url)
    alembic("upgrade", "head", url=url)
    alembic("check", url=url)
    ddl = alembic(
        "upgrade", "head", "--sql", url="postgresql+psycopg://unused:unused@localhost/ddl_only"
    ).stdout
    assert "UUID NOT NULL" in ddl
    assert "ALTER TABLE projects ADD CONSTRAINT fk_current_plan" in ddl
    assert "CREATE UNIQUE INDEX uq_current_actual" in ddl
