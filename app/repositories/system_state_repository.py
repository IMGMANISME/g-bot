from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text

from app.database import get_db_session
from app.models.system_state import SystemState
from app.utils.logger import setup_logger

logger = setup_logger("system_state_repository")


def get_system_state(key: str) -> Optional[str]:
    with get_db_session() as session:
        state = session.query(SystemState).filter_by(key=key).first()
        return state.value if state else None


def set_system_state(key: str, value: str):
    with get_db_session() as session:
        state = session.query(SystemState).filter_by(key=key).first()
        if not state:
            state = SystemState(key=key, value=value)
            session.add(state)
        else:
            state.value = value
            state.updated_at = datetime.utcnow()


def try_acquire_job_lock(lock_name: str, ttl_seconds: int) -> bool:
    """Acquire a lightweight DB lock for scheduled jobs.

    The lock is intentionally best-effort. If a process dies, another instance
    can acquire the lock after ttl_seconds.
    """
    key = f"job_lock:{lock_name}"
    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=ttl_seconds)

    with get_db_session() as session:
        statement = text(
            """
            INSERT INTO system_state (key, value, updated_at)
            VALUES (:key, :value, :now)
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value,
                updated_at = EXCLUDED.updated_at
            WHERE system_state.updated_at < :expired_before
            RETURNING key
            """
        )
        result = session.execute(
            statement,
            {
                "key": key,
                "value": expires_at.isoformat(),
                "now": now,
                "expired_before": now - timedelta(seconds=ttl_seconds),
            },
        )
        acquired = result.scalar_one_or_none() is not None
        if not acquired:
            logger.debug(f"排程鎖未取得，略過本輪工作: {lock_name}")
        return acquired
