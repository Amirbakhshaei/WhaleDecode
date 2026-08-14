from sqlalchemy import Boolean, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from whaledecode.adapters.db.models.base import Base


class CuratedWalletModel(Base):
    """A curated, high-conviction wallet/contract for the smart-money pipeline.

    Supports both EVM (0x…, 42-char hex) and Solana (Base58, 32-44 char) addresses.
    ``network_family`` tags the address family so downstream code (Alchemy EVM
    webhooks vs a future Helius/SVM webhook) can route by family.
    """

    __tablename__ = "curated_wallets"
    __table_args__ = (UniqueConstraint("address", "chain", name="uq_curated_address_chain"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    address: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # EVM 0x… or Solana Base58
    chain: Mapped[str] = mapped_column(String(16), nullable=False)  # ETH, ARB, BASE, SOL
    network_family: Mapped[str] = mapped_column(String(8), nullable=False, default="EVM")  # EVM or SVM
    label: Mapped[str] = mapped_column(String(128), nullable=True, default="")
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="Smart Money")
    tags: Mapped[str] = mapped_column(String(500), default="")  # comma-separated
    quality_score: Mapped[float] = mapped_column(Float, default=80.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
