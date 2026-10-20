"""Disposable HTTPS Compose verification. No enterprise MaaS requests or real credentials."""

import json
import os
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from init_llm_security import initialize

ROOT = Path(__file__).resolve().parents[1]
project = "llm-https-check-" + secrets.token_hex(4)
environment = {
    **os.environ,
    "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
    "POSTGRES_USER": "project_eval",
    "POSTGRES_DB": "project_eval",
    "ACCEPTANCE_PASSWORD": secrets.token_urlsafe(24),
    "LLM_ENCRYPTION_KEY": "",
}


def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run(args, **kwargs):
    return subprocess.run(
        args, env=environment, cwd=ROOT, check=True, text=True, **kwargs
    )


with tempfile.TemporaryDirectory(prefix="llm-https-compose-") as temporary:
    directory = Path(temporary)
    _, cert, _ = initialize(directory)
    api_port, ui_port = port(), port()
    override = directory / "override.yaml"
    override.write_text(f"""services:
  db:
    ports: !override []
  backend:
    image: project-evaluation-backend
    ports: !override ["127.0.0.1:{api_port}:8000"]
    volumes:
      - {directory}:/run/local-secrets:ro
  frontend:
    image: project-evaluation-frontend
    ports: !override ["127.0.0.1:{ui_port}:5173"]
    volumes:
      - {directory}:/run/local-secrets:ro
""")
    compose = [
        "docker",
        "compose",
        "-p",
        project,
        "-f",
        str(ROOT / "compose.yaml"),
        "-f",
        str(ROOT / "compose.https.yaml"),
        "-f",
        str(override),
    ]
    context = ssl.create_default_context(cafile=str(cert))
    try:
        run(compose + ["up", "-d", "--no-build"])
        with httpx.Client(
            base_url=f"https://127.0.0.1:{ui_port}",
            verify=context,
            trust_env=False,
            timeout=3,
        ) as client:
            for _ in range(60):
                try:
                    if client.get("/api/v1/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("HTTPS stack did not become ready")
            run(
                compose
                + [
                    "exec",
                    "-T",
                    "-e",
                    "ACCEPTANCE_PASSWORD",
                    "backend",
                    "python",
                    "-m",
                    "app.acceptance_seed",
                ]
            )
            response = client.post(
                "/api/v1/auth/login",
                json={
                    "username": "accept-editor",
                    "password": environment["ACCEPTANCE_PASSWORD"],
                },
            )
            assert response.status_code == 200
            client.headers["X-CSRF-Token"] = response.json()["data"]["csrf_token"]
            base = "/api/v1/settings/llm"
            cfg = client.get(base).json()["data"]
            response = client.put(
                base,
                headers={"If-Match": str(cfg["row_version"])},
                json={
                    "service_name": "HTTPS隔离持久化验证，无企业连接",
                    "base_url": "https://maas-api.cmhk.com/v1",
                    "mode": "mock",
                    "enabled": False,
                },
            )
            assert response.status_code == 200
            cfg = response.json()["data"]
            test_key = "isolated-https-only-" + secrets.token_urlsafe(32)
            response = client.put(
                base + "/credential",
                headers={"If-Match": str(cfg["row_version"])},
                json={"api_key": test_key},
            )
            assert response.status_code == 200
            cfg = response.json()["data"]
            assert cfg["key_configured"] and cfg["encryption_ready"]
            response = client.post(
                base + "/models",
                headers={"If-Match": str(cfg["row_version"])},
                json={
                    "model_id": "manual-https-persistence-fixture",
                    "display_name": "手动测试记录，未调用模型",
                },
            )
            assert response.status_code == 201
            assert response.json()["data"]["verification_status"] == "untested"
            for path in [
                base,
                base + "/models",
                base + "/audit-events",
                base + "/call-logs",
            ]:
                assert test_key not in client.get(path).text
            run(compose + ["restart", "db", "backend"])
            for _ in range(60):
                try:
                    response = client.get("/api/v1/health")
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("HTTPS stack did not recover after restart")
            cfg = client.get(base).json()["data"]
            assert (
                cfg["source"] == "database"
                and cfg["key_configured"]
                and cfg["encryption_ready"]
            )
            assert (
                client.get(base + "/models").json()["data"][0]["model_id"]
                == "manual-https-persistence-fixture"
            )
            sql = "SELECT encrypted_api_key IS NOT NULL FROM llm_service_config"
            encrypted = run(
                compose
                + [
                    "exec",
                    "-T",
                    "db",
                    "psql",
                    "-U",
                    "project_eval",
                    "-d",
                    "project_eval",
                    "-Atc",
                    sql,
                ],
                capture_output=True,
            ).stdout.strip()
            assert encrypted == "t"
            response = client.delete(
                base + "/credential", headers={"If-Match": str(cfg["row_version"])}
            )
            assert (
                response.status_code == 200
                and not response.json()["data"]["key_configured"]
            )
            cfg = response.json()["data"]
            response = client.post(
                base + "/test-connection", headers={"If-Match": str(cfg["row_version"])}
            )
            assert response.json()["data"]["result"]["code"] == "LLM_CREDENTIAL_MISSING"
        report = {
            "stack": "PostgreSQL16 + HTTPS Vite proxy + HTTPS FastAPI",
            "frontend_and_backend_tls_verification": "passed",
            "credential_encryption_and_redacted_get": "passed",
            "database_and_api_restart_persistence": "passed",
            "credential_removal": "passed",
            "enterprise_maas_connection": "not_attempted_no_real_key",
            "real_models_discovery": "not_attempted",
        }
        (ROOT / "docs" / "llm-https-verification.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
        print(
            "HTTPS全链路、加密配置、重启持久化与密钥移除验证通过；未向企业MaaS发送请求。",
            flush=True,
        )
    finally:
        subprocess.run(
            compose + ["down", "--volumes"],
            env=environment,
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
