"""Create accounts, sessions and watchlists.

Revision ID: 0001_accounts_watchlists
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_accounts_watchlists"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("users",
                    sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("email", sa.String(320), nullable=False),
                    sa.Column("username", sa.String(24), nullable=False),
                    sa.Column("password_hash", sa.String(255), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_table("login_sessions",
                    sa.Column("token_hash", sa.String(64), primary_key=True),
                    sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("csrf_token", sa.String(64), nullable=False),
                    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_login_sessions_user_id", "login_sessions", ["user_id"])
    op.create_table("watchlists",
                    sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("name", sa.String(80), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                    sa.UniqueConstraint("user_id", "name", name="uq_watchlist_user_name"))
    op.create_index("ix_watchlists_user_id", "watchlists", ["user_id"])
    op.create_table("watchlist_items",
                    sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("watchlist_id", sa.Integer(), sa.ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("media_id", sa.String(64), nullable=False),
                    sa.Column("media_type", sa.String(12), nullable=False),
                    sa.Column("title", sa.String(500), nullable=False),
                    sa.Column("poster_url", sa.String(500)),
                    sa.Column("status", sa.String(20), nullable=False),
                    sa.Column("rating", sa.Integer()),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                    sa.UniqueConstraint("watchlist_id", "media_id", name="uq_watchlist_item"))
    op.create_index("ix_watchlist_items_watchlist_id", "watchlist_items", ["watchlist_id"])


def downgrade():
    op.drop_table("watchlist_items")
    op.drop_table("watchlists")
    op.drop_table("login_sessions")
    op.drop_table("users")
