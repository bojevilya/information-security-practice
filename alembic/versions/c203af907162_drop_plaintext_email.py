"""drop plaintext email

Revision ID: c203af907162
Revises: 37f324a0670a
Create Date: 2026-10-16 14:58:18.702659

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c203af907162'
down_revision: Union[str, None] = '37f324a0670a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Запускати ЛИШЕ після python -m scripts.migrate_encrypt
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_email")
        batch.drop_column("email")


def downgrade() -> None:
    # Відкриті email не відновлюються — лише порожня колонка
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("email", sa.String(100), nullable=True))
