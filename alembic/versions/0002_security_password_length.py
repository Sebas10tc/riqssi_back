"""Allow bcrypt password hashes.

Revision ID: 0002_security_password_length
Revises: 0001_initial_schema
"""
from alembic import op
import sqlalchemy as sa

revision = '0002_security_password_length'
down_revision = '0001_initial_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        'usuario',
        'clave',
        existing_type=sa.String(length=20),
        type_=sa.String(length=255),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        'usuario',
        'clave',
        existing_type=sa.String(length=255),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
