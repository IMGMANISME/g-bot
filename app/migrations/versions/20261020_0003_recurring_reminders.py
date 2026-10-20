"""週期提醒：每隔一段時間提醒，可限定每天的時段（可跨午夜），並記錄使用者最近一次完成的時間

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-20 16:41:02.953709

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('scheduled_notifications', sa.Column('interval_minutes', sa.Integer(), nullable=True))
    op.add_column('scheduled_notifications', sa.Column('window_start', sa.Time(), nullable=True))
    op.add_column('scheduled_notifications', sa.Column('window_end', sa.Time(), nullable=True))
    op.add_column('scheduled_notifications', sa.Column('last_done_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('scheduled_notifications', 'last_done_at')
    op.drop_column('scheduled_notifications', 'window_end')
    op.drop_column('scheduled_notifications', 'window_start')
    op.drop_column('scheduled_notifications', 'interval_minutes')
