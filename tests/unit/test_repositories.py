import pytest

from whaledecode.domain.entities.curated_wallet import CuratedWallet
from whaledecode.domain.entities.user import User
from whaledecode.domain.value_objects.chain import Chain


@pytest.mark.asyncio
async def test_user_repo_create_and_get(db_session):
    from whaledecode.adapters.db.repositories.user import UserRepository

    repo = UserRepository(db_session)
    user = await repo.create(User(tg_id=12345, username="testuser"))
    assert user.id is not None
    assert user.tg_id == 12345

    fetched = await repo.get_by_tg_id(12345)
    assert fetched is not None
    assert fetched.username == "testuser"


@pytest.mark.asyncio
async def test_curated_wallet_repo_create_and_list(db_session):
    from whaledecode.adapters.db.repositories.curated_wallet import CuratedWalletRepository

    repo = CuratedWalletRepository(db_session)
    wallet = await repo.create(
        CuratedWallet(
            address="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
            chain=Chain.ETH,
            label="Test Whale",
            tags=["whale", "defi"],
            quality_score=0.85,
        )
    )
    assert wallet.id is not None

    active = await repo.list_active()
    assert len(active) == 1
    assert active[0].label == "Test Whale"
    assert active[0].tags == ["whale", "defi"]


@pytest.mark.asyncio
async def test_candidate_event_dedupe(db_session):
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository
    from whaledecode.domain.entities.candidate_event import CandidateEvent
    from whaledecode.domain.value_objects.hash import Hash

    repo = CandidateEventRepository(db_session)
    event = await repo.create(
        CandidateEvent(
            wallet_id=1,
            chain="ETH",
            tx_hash=Hash("0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
            log_index=0,
            block_number=100,
            dedupe_key="test:dedupe:1",
        )
    )
    assert event.id is not None

    dup = await repo.get_by_dedupe_key("test:dedupe:1")
    assert dup is not None
    assert dup.dedupe_key == "test:dedupe:1"
