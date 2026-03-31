from typing import List
from app.database import get_db_session
from app.models.message import Message
from app.utils.logger import setup_logger
from app.utils.decorators import handle_exceptions

logger = setup_logger("message_repository")

@handle_exceptions("訊息儲存失敗")
def save_message(sender_id: str, role: str, content: str):
    """儲存訊息並保持最新10條記錄"""
    try:
        with get_db_session() as session:
            message = Message(sender_id=sender_id, role=role, content=content)
            session.add(message)
            session.flush()
            
            old_messages = session.query(Message).filter(
                Message.sender_id == sender_id
            ).order_by(Message.timestamp.desc()).offset(10).all()
            
            for msg in old_messages:
                session.delete(msg)
            
            logger.debug(f"為用戶 {sender_id} 儲存訊息，清理了 {len(old_messages)} 條舊記錄")
    except Exception as e:
        logger.error(f"儲存訊息失敗: {e}")

@handle_exceptions("訊息歷史取得失敗", reraise=False)
def get_history(sender_id: str) -> List[dict]:
    """取得對話歷史"""
    try:
        with get_db_session() as session:
            messages = session.query(Message).filter(
                Message.sender_id == sender_id
            ).order_by(Message.timestamp.asc()).all()
            
            return [{"role": m.role, "content": m.content} for m in messages]
    except Exception as e:
        logger.error(f"取得歷史記錄失敗: {e}")
        return []

@handle_exceptions("清除歷史失敗")
def clear_history(sender_id: str):
    """清除對話歷史"""
    try:
        with get_db_session() as session:
            deleted_count = session.query(Message).filter(
                Message.sender_id == sender_id
            ).delete()
            logger.info(f"清除了用戶 {sender_id} 的 {deleted_count} 條歷史記錄")
    except Exception as e:
        logger.error(f"清除歷史失敗: {e}")
