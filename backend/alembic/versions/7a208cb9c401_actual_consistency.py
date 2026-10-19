"""Keep actual date and completion flag consistent even for non-API writes."""

from alembic import op
import sqlalchemy as sa

revision = "7a208cb9c401"
down_revision = "db975272e206"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite table recreation omits unnamed CHECKs. Re-declare the two original
    # invariants explicitly; PostgreSQL adds the new constraint in place.
    table_args = ()
    if op.get_bind().dialect.name == "sqlite":
        table_args = (
            sa.CheckConstraint(
                "verification_status IN ('submitted','verified','returned','disputed')",
                name="ck_actual_verification_status",
            ),
            sa.CheckConstraint(
                "completion_flag IS NOT TRUE OR actual_date IS NOT NULL",
                name="ck_actual_completion_date",
            ),
        )
    with op.batch_alter_table("milestone_actual_records", table_args=table_args) as batch:
        batch.create_check_constraint(
            "ck_actual_date_requires_completion", "actual_date IS NULL OR completion_flag IS TRUE"
        )


def downgrade():
    with op.batch_alter_table("milestone_actual_records") as batch:
        batch.drop_constraint("ck_actual_date_requires_completion", type_="check")
