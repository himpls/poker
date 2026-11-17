"""Tournament standings, separate from cash accounting."""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tournaments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("club_id", sa.Integer(), sa.ForeignKey("clubs.id"), nullable=False),
        sa.Column("title", sa.String(80), nullable=False),
        sa.Column("starts_at", sa.String(40), nullable=False),
        sa.Column("location", sa.String(250), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="planned"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.String(500), nullable=False, server_default=""),
        sa.Column("request_key", sa.String(100), nullable=False, unique=True),
        sa.CheckConstraint("status IN ('planned','completed','cancelled')"),
    )
    op.create_table(
        "tournament_results",
        sa.Column("tournament_id", sa.Integer(), sa.ForeignKey("tournaments.id"), primary_key=True),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), primary_key=True),
        sa.Column("place", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tournament_id", "place"),
        sa.CheckConstraint("place > 0"),
    )


def downgrade():
    op.drop_table("tournament_results")
    op.drop_table("tournaments")
