"""Align report model IDs without recreating a parent table or dropping its CHECKs."""

from alembic import context, op
import sqlalchemy as sa

revision = "5e93d62bcf40"
down_revision = "3fe4fc031b52"
branch_labels = None
depends_on = None


def resize(length, previous):
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        # SQLite >=3.35 native column operations preserve the table's CHECKs,
        # indexes, identity and incoming report_review FKs. Savepoint keeps the copy atomic.
        connection.exec_driver_sql("SAVEPOINT llm_model_id_resize")
        try:
            op.add_column(
                "report_drafts", sa.Column("_llm_model_id_copy", sa.String(length), nullable=True)
            )
            op.execute("UPDATE report_drafts SET _llm_model_id_copy = model_id")
            op.drop_column("report_drafts", "model_id")
            op.alter_column("report_drafts", "_llm_model_id_copy", new_column_name="model_id")
            connection.exec_driver_sql("RELEASE SAVEPOINT llm_model_id_resize")
        except Exception:
            connection.exec_driver_sql("ROLLBACK TO SAVEPOINT llm_model_id_resize")
            connection.exec_driver_sql("RELEASE SAVEPOINT llm_model_id_resize")
            raise
    else:
        op.alter_column(
            "report_drafts",
            "model_id",
            existing_type=sa.String(previous),
            type_=sa.String(length),
            existing_nullable=True,
        )


def upgrade():
    resize(256, 120)


def downgrade():
    if (
        not context.is_offline_mode()
        and op.get_bind()
        .execute(sa.text("SELECT count(*) FROM report_drafts WHERE length(model_id)>120"))
        .scalar()
    ):
        raise RuntimeError(
            "存在超过旧字段长度的模型ID；请先制定保留方案，不能截断或清空历史模型来源"
        )
    resize(120, 256)
