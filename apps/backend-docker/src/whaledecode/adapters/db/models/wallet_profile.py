from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from whaledecode.adapters.db.models.base import Base


class WalletProfileModel(Base):
    """Rolling behavioral profile for a curated wallet (Module 1).

    Recomputed nightly by the behavioral profiler; read at alert time with
    zero LLM/tool latency.
    """

    __tablename__ = "wallet_profiles"
    __table_args__ = (
        UniqueConstraint("chain", "address", name="uq_wallet_profile_chain_addr"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chain: Mapped[str] = mapped_column(String(20), nullable=False)
    address: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    historical_win_rate_30d: Mapped[float] = mapped_column(Float, default=0.0)
    avg_holding_period_days: Mapped[float] = mapped_column(Float, default=0.0)
    primary_strategy: Mapped[str] = mapped_column(String(50), default="Unknown")
    total_pnl_usd: Mapped[float] = mapped_column(Float, default=0.0)
    recent_actions_summary: Mapped[str] = mapped_column(Text, default="")
    sample_size_30d: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(20), default="self_observed")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
