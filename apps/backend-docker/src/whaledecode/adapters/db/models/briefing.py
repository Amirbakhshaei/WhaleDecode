from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from whaledecode.adapters.db.models.base import Base


class BriefingModel(Base):
    __tablename__ = "briefings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    summary_md: Mapped[str] = mapped_column(Text, default="")
    events_json: Mapped[str] = mapped_column(Text, default="[]")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
