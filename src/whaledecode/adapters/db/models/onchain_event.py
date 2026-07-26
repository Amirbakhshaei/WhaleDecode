from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from whaledecode.adapters.db.models.base import Base


class OnchainEventModel(Base):
    __tablename__ = "onchain_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(Integer, ForeignKey("candidate_events.id"), nullable=False)
    wallet_id: Mapped[int] = mapped_column(Integer, ForeignKey("curated_wallets.id"), nullable=False)
    chain: Mapped[str] = mapped_column(String(20), nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    block_number: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    decoded: Mapped[str] = mapped_column(Text, default="{}")
    enriched_json: Mapped[str] = mapped_column(Text, default="{}")
