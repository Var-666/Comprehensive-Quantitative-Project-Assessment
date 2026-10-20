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


def test_model_id_migration_preserves_reports_reviews_and_constraints(tmp_path):
    """An upgrade must keep report provenance and independent approval, including SQLite CHECKs."""
    from pathlib import Path

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.evaluation_models import MetricSnapshot, ReportDraft, ReportReview
    from app.models import Project
    from app.seed import load_sample

    url = f"sqlite:///{tmp_path / 'report_migration.db'}"
    alembic("upgrade", "3fe4fc031b52", url=url)
    engine = make_engine(url)
    with Session(engine) as db:
        load_sample(db, Path(__file__).resolve().parents[2] / "模拟业务测试数据 V0.1.xlsx")
        project = db.scalar(select(Project))
        snapshot = MetricSnapshot(
            project_id=project.id,
            as_of_date=__import__("datetime").date(2026, 10, 19),
            plan_version_id=project.current_plan_version_id,
            formula_version="trial_v1",
            source_digest="migration-fixture",
            payload_json={"evidence": "migration fixture"},
            created_by="test",
        )
        db.add(snapshot)
        db.flush()
        report = ReportDraft(
            project_id=project.id,
            metric_snapshot_id=snapshot.id,
            request_key="migration-fixture",
            request_digest="migration-fixture",
            report_type="stage",
            fact_bundle_json={"evidence": "migration fixture"},
            generator_type="mock",
            model_id="existing-model-id",
            content="报告内容必须原样保留",
            validation_json={},
            contains_finance=False,
            review_status="approved",
            created_by="compiler",
            editor_ids=["compiler"],
        )
        db.add(report)
        db.flush()
        review = ReportReview(
            report_id=report.id,
            decision="approved",
            comment="独立核对通过",
            reviewer_id="reviewer",
            content_digest="migration-fixture",
        )
        db.add(review)
        db.commit()
        report_id = report.id
        review_id = review.id
    assert len(inspect(engine).get_check_constraints("report_drafts")) == 2
    alembic("upgrade", "head", url=url)
    assert len(inspect(engine).get_check_constraints("report_drafts")) == 2
    with Session(engine) as db:
        assert db.get(ReportDraft, report_id).content == "报告内容必须原样保留"
        assert db.get(ReportDraft, report_id).model_id == "existing-model-id"
        assert db.get(ReportReview, review_id).report_id == report_id
        db.get(ReportDraft, report_id).model_id = "long-provider-id-" + ("x" * 150)
        db.commit()
    try:
        alembic("downgrade", "3fe4fc031b52", url=url)
    except subprocess.CalledProcessError as exc:
        assert "不能截断或清空" in exc.stderr
    else:
        raise AssertionError("回滚不得丢弃超出旧字段的模型来源")
    with Session(engine) as db:
        assert len(db.get(ReportDraft, report_id).model_id) > 120
        assert db.get(ReportReview, review_id).comment == "独立核对通过"
    engine.dispose()
