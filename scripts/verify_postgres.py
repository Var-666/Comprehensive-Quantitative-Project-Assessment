"""Disposable official PostgreSQL container; never touches development or company databases."""

import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
name = f"project-eval-acceptance-{secrets.token_hex(4)}"
password = secrets.token_urlsafe(32)
environment = {**os.environ, "APP_ENV": "test", "DEMO_MODE": "true"}
db_user = "project_eval"


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


try:
    with tempfile.NamedTemporaryFile(mode="w", prefix="project-eval-pg-", delete=True) as envfile:
        envfile.write(
            f"POSTGRES_USER={db_user}\nPOSTGRES_PASSWORD={password}\nPOSTGRES_DB=acceptance\n"
        )
        envfile.flush()
        run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--label",
                "project-eval.acceptance=true",
                "--env-file",
                envfile.name,
                "-p",
                "127.0.0.1::5432",
                "postgres:16-alpine",
            ],
            stdout=subprocess.DEVNULL,
        )
    for _ in range(60):
        ready = subprocess.run(
            ["docker", "exec", name, "pg_isready", "-U", db_user], capture_output=True, check=False
        )
        if ready.returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("PostgreSQL 未就绪")
    port = json.loads(subprocess.check_output(["docker", "inspect", name], text=True))[0][
        "NetworkSettings"
    ]["Ports"]["5432/tcp"][0]["HostPort"]
    environment["DATABASE_URL"] = (
        f"postgresql+psycopg://{db_user}:{password}@127.0.0.1:{port}/acceptance"
    )
    print("PostgreSQL 已就绪，运行迁移往返和样本校验", flush=True)
    for args in (
        ("alembic", "upgrade", "head"),
        ("alembic", "downgrade", "base"),
        ("alembic", "upgrade", "head"),
        ("alembic", "check"),
        ("app.seed",),
    ):
        command = [sys.executable, "-m", *args]
        run(command, cwd=ROOT / "backend", env=environment)
    run(["docker", "exec", name, "createdb", "-U", db_user, "business_tests"])
    environment["TEST_DATABASE_URL"] = environment["DATABASE_URL"].replace(
        "/acceptance", "/business_tests"
    )
    print("运行真实 PostgreSQL 上的 API、权限、事务与业务测试", flush=True)
    run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT / "backend", env=environment)
    report = ROOT / "docs" / "postgres-verification.json"
    report.write_text(
        json.dumps(
            {
                "database": "PostgreSQL 16 official image",
                "migration_roundtrip": "passed",
                "sample_seed": "passed",
                "pytest": "passed",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print("PostgreSQL 实例验证通过", flush=True)
finally:
    subprocess.run(
        ["docker", "rm", "-f", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
