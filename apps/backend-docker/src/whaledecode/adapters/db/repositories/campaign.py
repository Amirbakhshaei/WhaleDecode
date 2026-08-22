from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from whaledecode.adapters.db.models.campaign import CampaignModel


class CampaignRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_for_wallet(
        self, wallet_id: int, chain: str, since: datetime
    ) -> CampaignModel | None:
        """Most recent active campaign for a wallet on a chain updated within the window."""
        result = await self._session.execute(
            select(CampaignModel)
            .where(
                CampaignModel.wallet_id == wallet_id,
                CampaignModel.chain == chain,
                CampaignModel.status == "active",
                CampaignModel.updated_at >= since,
            )
            .order_by(CampaignModel.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create(self, data: dict[str, Any]) -> CampaignModel:
        model = CampaignModel(**data)
        self._session.add(model)
        await self._session.flush()
        return model

    async def set_telegram_message_id(self, campaign_id: int, message_id: int | None) -> None:
        await self._session.execute(
            update(CampaignModel)
            .where(CampaignModel.id == campaign_id)
            .values(telegram_message_id=message_id, updated_at=datetime.now(UTC))
        )
