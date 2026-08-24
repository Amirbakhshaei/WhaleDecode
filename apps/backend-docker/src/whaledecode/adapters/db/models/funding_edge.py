from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from whaledecode.adapters.db.models.base import Base


class FundingEdgeModel(Base):
    """One directed edge child <- parent discovered by the multi-hop tracer."""

    __tablename__ = "funding_edges"
    __table_args__ = (
        UniqueConstraint("child_address", "tx_hash", name="uq_funding_edge_child_tx"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chain: Mapped[str] = mapped_column(String(20), nullable=False)
    child_address: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    parent_address: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    tx_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    block_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hops_from_root: Mapped[int] = mapped_column(Integer, default=1)
    root_address: Mapped[str] = mapped_column(String(80), default="", index=True)
    root_label: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
