"""Run PostgreSQL, API, scanner and UI acceptance, then remove only this run's resources."""

import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
project = "project-eval-check-" + secrets.token_hex(4)
environment = {
    **os.environ,
    "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
    "POSTGRES_USER": "project_eval",
    "POSTGRES_DB": "project_eval",
    "ACCEPTANCE_PASSWORD": secrets.token_urlsafe(24),
}


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


db_port, api_port, ui_port = free_port(), free_port(), free_port()
with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml") as override:
    override.write(f"""services:
  db:
    ports: !override ["127.0.0.1:{db_port}:5432"]
  backend:
    image: project-evaluation-backend
    ports: !override ["127.0.0.1:{api_port}:8000"]
    environment:
      ALLOWED_ORIGINS: http://127.0.0.1:{ui_port}
  frontend:
    image: project-evaluation-frontend
    ports: !override ["127.0.0.1:{ui_port}:5173"]
""")
    override.flush()
    compose = [
        "docker",
        "compose",
        "-p",
        project,
        "-f",
        str(ROOT / "compose.yaml"),
        "-f",
        override.name,
    ]

    def run(args, **kwargs):
        return subprocess.run(
            args, env=environment, check=True, cwd=ROOT, text=True, **kwargs
        )

    try:
        run(compose + ["up", "-d", "--no-build"])
        for _ in range(60):
            try:
                with urlopen(
                    f"http://127.0.0.1:{ui_port}/api/v1/health", timeout=2
                ) as response:
                    if response.status == 200:
                        break
            except (URLError, TimeoutError, ConnectionError):
                pass
            time.sleep(1)
        else:
            run(compose + ["logs", "--tail", "30"])
            raise RuntimeError("容器栈健康检查超时")
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
        environment["EXTERNAL_UI_URL"] = f"http://127.0.0.1:{ui_port}"
        print("容器数据库、后端、前端健康；运行真实容器栈浏览器验收", flush=True)
        subprocess.run(
            ["npm", "run", "test:e2e"],
            cwd=ROOT / "frontend",
            env=environment,
            check=True,
        )
        count_command = compose + [
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "project_eval",
            "-d",
            "project_eval",
            "-Atc",
            "SELECT count(*) FROM projects",
        ]
        before = run(count_command, capture_output=True).stdout.strip()
        workflow_count_command = count_command[:-1] + [
            "SELECT json_build_object('reminders',(SELECT count(*) FROM reminder_instances),'notifications',(SELECT count(*) FROM notification_drafts),'tasks',(SELECT count(*) FROM tasks),'feedback',(SELECT count(*) FROM task_feedback),'inbox',(SELECT count(*) FROM inbox_messages))"
        ]
        workflow_before = json.loads(
            run(workflow_count_command, capture_output=True).stdout
        )
        if not all(value > 0 for value in workflow_before.values()):
            raise RuntimeError("第二阶段浏览器闭环未产生完整业务记录")
        worker_log = run(
            compose + ["logs", "--no-color", "worker"], capture_output=True
        ).stdout
        if "scan completed" not in worker_log:
            raise RuntimeError("自动扫描进程没有成功运行记录")
        run(compose + ["restart", "db"])
        for _ in range(30):
            result = subprocess.run(
                compose + ["exec", "-T", "db", "pg_isready", "-U", "project_eval"],
                env=environment,
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                break
            time.sleep(1)
        after = run(count_command, capture_output=True).stdout.strip()
        workflow_after = json.loads(
            run(workflow_count_command, capture_output=True).stdout
        )
        if workflow_before != workflow_after:
            raise RuntimeError("数据库重启后提醒、通知、任务、反馈或站内消息丢失")
        if before != after or int(after) < 3:
            raise RuntimeError("数据库容器重启后项目数据不一致")
        run(compose + ["restart", "backend"])
        print(f"数据库重启后保留 {after} 个验收项目，数据持久化验证通过", flush=True)
        print("Docker Compose 全栈浏览器验收通过", flush=True)
        (ROOT / "docs" / "compose-verification.json").write_text(
            json.dumps(
                {
                    "stack": "PostgreSQL16/FastAPI/Vue",
                    "browser_tests": "passed",
                    "database_restart_persistence": "passed",
                    "project_count_after_restart": int(after),
                    "worker_scan": "passed",
                    "workflow_records_after_restart": workflow_after,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
    finally:
        subprocess.run(
            compose + ["down", "--volumes"],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
