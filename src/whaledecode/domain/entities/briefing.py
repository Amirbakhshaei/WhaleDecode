from datetime import date, datetime

from pydantic import BaseModel, Field


class Briefing(BaseModel):
    id: int | None = None
    user_id: int
    date: date
    summary_md: str = ""
    events_json: list[dict] = Field(default_factory=list)
    sent_at: datetime | None = None
