from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from whaledecode.adapters.db.models.base import Base


class TrackedWalletModel(Base):
    __tablename__ = "tracked_wallets"
    __table_args__ = (
        UniqueConstraint("user_id", "wallet_id", name="uq_user_wallet"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    wallet_id: Mapped[int] = mapped_column(Integer, ForeignKey("curated_wallets.id"), nullable=False)
    chain: Mapped[str] = mapped_column(String(20), nullable=False)
    alias: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
