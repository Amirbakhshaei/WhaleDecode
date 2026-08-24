from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from whaledecode.adapters.db.models.base import Base


class AlertModel(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_alert_dedupe"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    event_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Edge Intelligence enrichment (migration 0012).
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    pool_impact_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    cluster_origin: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hop_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coordinated_flag: Mapped[bool] = mapped_column(Boolean, default=False, server_default="FALSE")
