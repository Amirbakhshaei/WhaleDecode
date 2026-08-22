from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from whaledecode.adapters.db.models.base import Base


class CandidateEventModel(Base):
    __tablename__ = "candidate_events"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_candidate_dedupe"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(Integer, ForeignKey("curated_wallets.id"), nullable=False)
    chain: Mapped[str] = mapped_column(String(20), nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    log_index: Mapped[int] = mapped_column(Integer, default=0)
    block_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    event_type: Mapped[str] = mapped_column(String(50), default="UNKNOWN")
    raw_json: Mapped[str | None] = mapped_column(Text, default="{}", nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="NEW")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    campaign_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("campaigns.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    campaign: Mapped["CampaignModel"] = relationship("CampaignModel", back_populates="events")  # noqa: F821
