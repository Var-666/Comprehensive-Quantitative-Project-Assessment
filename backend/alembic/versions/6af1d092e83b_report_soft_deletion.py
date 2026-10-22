"""Retain report facts, independent reviews and audit history when deleting a report."""

import sqlalchemy as sa

from alembic import context, op

revision = "6af1d092e83b"
down_revision = "5e93d62bcf40"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "report_drafts", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade():
    if (
        not context.is_offline_mode()
        and op.get_bind()
        .execute(sa.text("SELECT count(*) FROM report_drafts WHERE deleted_at IS NOT NULL"))
        .scalar()
    ):
        raise RuntimeError("存在已删除报告；回滚将丢失删除标记，须先制定保留方案")
    op.drop_column("report_drafts", "deleted_at")
