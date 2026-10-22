"""Persist tracking-only choices in versioned node snapshots; historical nodes keep matching."""

from alembic import context, op
import sqlalchemy as sa

revision = "b42d8e910a21"
down_revision = "6af1d092e83b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "milestone_plan_items",
        sa.Column("tracking_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    if (
        not context.is_offline_mode()
        and op.get_bind()
        .execute(sa.text("SELECT count(*) FROM milestone_plan_items WHERE tracking_only = true"))
        .scalar()
    ):
        raise RuntimeError("已有仅时间记录节点；请先制定保留该业务选择的回滚方案")
    op.drop_column("milestone_plan_items", "tracking_only")
