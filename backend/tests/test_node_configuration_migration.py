import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_tracking_only_migration_preserves_history_and_refuses_lossy_downgrade(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    database = tmp_path / "migration.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}

    def migrate(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=backend,
            env=env,
            capture_output=True,
            text=True,
        )

    result = migrate("upgrade", "6af1d092e83b")
    assert result.returncode == 0, result.stderr
    # This isolated row exercises backfill on the old schema, independent of the current ORM.
    with sqlite3.connect(database) as db:
        db.execute(
            "INSERT INTO milestone_plan_items (id,milestone_id,plan_version_id,milestone_name,node_type_code,planned_date,date_kind,change_reason,is_included) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "old-item",
                "old-node",
                "old-plan",
                "原有节点",
                "设计资料",
                "2026-10-01",
                "internal_plan",
                "原有原因",
                True,
            ),
        )
    result = migrate("upgrade", "head")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as db:
        assert db.execute(
            "SELECT milestone_name,change_reason,tracking_only FROM milestone_plan_items"
        ).fetchone() == ("原有节点", "原有原因", 0)
        db.execute("UPDATE milestone_plan_items SET tracking_only = true")
    result = migrate("downgrade", "6af1d092e83b")
    assert result.returncode != 0 and "仅时间记录节点" in result.stderr
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT tracking_only FROM milestone_plan_items").fetchone() == (1,)
