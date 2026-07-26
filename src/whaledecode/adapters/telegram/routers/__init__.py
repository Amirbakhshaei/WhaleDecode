from whaledecode.adapters.telegram.routers.admin import admin_router
from whaledecode.adapters.telegram.routers.chat import chat_router
from whaledecode.adapters.telegram.routers.common import common_router
from whaledecode.adapters.telegram.routers.wallet import wallet_router

__all__ = ["admin_router", "chat_router", "common_router", "wallet_router"]
