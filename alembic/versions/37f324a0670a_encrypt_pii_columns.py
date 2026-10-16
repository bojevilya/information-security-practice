"""encrypt pii columns

Revision ID: 37f324a0670a
Revises: f5ac69464028
Create Date: 2026-10-16 14:58:17.478453

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '37f324a0670a'
down_revision: Union[str, None] = 'f5ac69464028'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite не вміє ALTER для обмежень → batch-режим (копія таблиці)
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("encrypted_email", sa.String(500), nullable=True))
        batch.add_column(sa.Column("email_index", sa.String(64), nullable=True))
        batch.add_column(sa.Column("encrypted_phone", sa.String(500), nullable=True))
        batch.create_index("ix_users_email_index", ["email_index"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_email_index")
        batch.drop_column("encrypted_phone")
        batch.drop_column("email_index")
        batch.drop_column("encrypted_email")
