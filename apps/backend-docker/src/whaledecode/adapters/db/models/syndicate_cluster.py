"""Syndicate cluster model for coordinated wallet group detection."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from whaledecode.adapters.db.models.base import Base


class SyndicateClusterModel(Base):
    """Detected multi-wallet cluster buying the same token within a time window."""

    __tablename__ = "syndicate_clusters"
    __table_args__ = (
        UniqueConstraint("root_address", "token_address", "window_start", name="uq_syndicate_cluster_root_token_window"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    chain: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    root_address: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    root_label: Mapped[str] = mapped_column(String(255), default="")
    token_address: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    token_symbol: Mapped[str] = mapped_column(String(20), default="")
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    wallet_count: Mapped[int] = mapped_column(Integer, default=0)
    total_usd: Mapped[float] = mapped_column(Float, default=0.0)
    cluster_type: Mapped[str] = mapped_column(String(50), default="FRESH_CEX_ACCUMULATOR")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())