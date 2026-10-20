# SQLAlchemy models
from importlib import import_module

MODEL_MODULES = (
    "app.models.user",
    "app.models.message",
    "app.models.restaurant",
    "app.models.notification",
    "app.models.system_state",
)


def load_all_models() -> None:
    """匯入所有 model，讓 Base.metadata 包含每一張資料表（建表與 migration 比對都需要）。"""
    for module in MODEL_MODULES:
        import_module(module)
