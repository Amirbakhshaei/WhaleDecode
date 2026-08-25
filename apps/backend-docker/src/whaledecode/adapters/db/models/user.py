from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from whaledecode.adapters.db.models.base import Base


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    plan: Mapped[str] = mapped_column(String(20), default="free")
    tier: Mapped[str] = mapped_column(String(20), default="free", server_default="free")
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    daily_chat_count: Mapped[int] = mapped_column(Integer, default=0)
    daily_alert_count: Mapped[int] = mapped_column(Integer, default=0)
    queries_remaining: Mapped[int] = mapped_column(Integer, default=5, server_default="5", nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
