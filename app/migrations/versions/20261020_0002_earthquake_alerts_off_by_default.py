"""地震通知改為預設關閉

資料庫在 0001 重建後，現有聊天室的「開啟」都是預設值而不是自己選的，
所以一併改成關閉；想收地震速報的人再輸入「地震通知開」。

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-20 16:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('user_state', 'earthquake_enabled', server_default=sa.text('false'))
    op.execute("UPDATE user_state SET earthquake_enabled = false")


def downgrade() -> None:
    # 只還原預設值；已被關閉的設定無法分辨原本是不是預設值，維持現狀
    op.alter_column('user_state', 'earthquake_enabled', server_default=sa.text('true'))
