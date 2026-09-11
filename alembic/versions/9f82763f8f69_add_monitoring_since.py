"""add monitoring_since

Revision ID: 9f82763f8f69
Revises: 558d870f9035
Create Date: 2026-09-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9f82763f8f69"
down_revision: Union[str, Sequence[str], None] = "558d870f9035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("endpoint", sa.Column(
        "monitoring_since", sa.DateTime(timezone=True),
        nullable=False, server_default=sa.text("now()"),
    ))


def downgrade() -> None:
    op.drop_column("endpoint", "monitoring_since")