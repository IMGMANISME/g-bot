"""順便提醒：一對一聊天時，使用者傳訊息就在回覆中順便提醒（不花推播額度），並記錄最近一次提醒時間

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-20 20:25:01.297008

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('scheduled_notifications', sa.Column('nudge_interval_minutes', sa.Integer(), nullable=True))
    op.add_column('scheduled_notifications', sa.Column('last_reminded_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('scheduled_notifications', 'last_reminded_at')
    op.drop_column('scheduled_notifications', 'nudge_interval_minutes')
