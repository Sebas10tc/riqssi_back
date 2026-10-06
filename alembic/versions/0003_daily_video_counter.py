"""Track the day of the analyzed-videos counter.

Revision ID: 0003_daily_video_counter
Revises: 0002_security_password_length
"""
from alembic import op

revision = '0003_daily_video_counter'
down_revision = '0002_security_password_length'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('ALTER TABLE usuario ADD COLUMN IF NOT EXISTS videos_analyzed_date DATE')


def downgrade() -> None:
    op.execute('ALTER TABLE usuario DROP COLUMN IF EXISTS videos_analyzed_date')
