import pytest
from sqlalchemy.dialects import postgresql
from whaledecode.adapters.db.repositories.candidate_event import pending_events_statement
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


def _pending_data(dedupe_key: str, block_number: int = 100) -> dict:
    return {
        "wallet_id": 1,
        "chain": "ETH",
        "tx_hash": "0x" + "a" * 64,
        "log_index": 0,
        "block_number": block_number,
        "event_type": "TRANSFER",
        "raw_json": {"value_usd": 100.0},
        "score": 80.0,
        "dedupe_key": dedupe_key,
    }


@pytest.mark.asyncio
async def test_create_pending_inserts_pending_status(db_session):
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository

    repo = CandidateEventRepository(db_session)
    await repo.create_pending(_pending_data("pending:1"))
    await db_session.commit()

    events = await repo.claim_next_pending()
    assert len(events) == 1
    assert events[0].status == "pending"
    assert events[0].score == 80.0
    assert events[0].dedupe_key == "pending:1"


@pytest.mark.asyncio
async def test_create_pending_idempotent_on_dedupe(db_session):
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository

    repo = CandidateEventRepository(db_session)
    await repo.create_pending(_pending_data("pending:dup"))
    await db_session.commit()
    await repo.create_pending(_pending_data("pending:dup"))
    await db_session.commit()

    events = await repo.claim_next_pending(limit=10)
    assert len(events) == 1


@pytest.mark.asyncio
async def test_claim_next_pending_oldest_first(db_session):
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository

    repo = CandidateEventRepository(db_session)
    for i in range(3):
        await repo.create_pending(_pending_data(f"pending:seq:{i}", block_number=100 + i))
    await db_session.commit()

    first = await repo.claim_next_pending(limit=1)
    assert first[0].dedupe_key == "pending:seq:0"

    all_events = await repo.claim_next_pending(limit=10)
    assert [e.dedupe_key for e in all_events] == ["pending:seq:0", "pending:seq:1", "pending:seq:2"]


@pytest.mark.asyncio
async def test_set_status_updates_pending_row(db_session):
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository

    repo = CandidateEventRepository(db_session)
    await repo.create_pending(_pending_data("pending:status"))
    await db_session.commit()

    claimed = await repo.claim_next_pending()
    await repo.set_status(claimed[0].id, "processing")
    await db_session.commit()

    events = await repo.claim_next_pending()
    assert events == []


def test_pending_events_statement_locks_skipped_rows_for_postgres() -> None:
    sql = str(pending_events_statement(1, for_update=True).compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert 'candidate_events.status = %(status_1)s' in sql
    assert "ORDER BY candidate_events.created_at ASC" in sql
    assert " LIMIT %(param_1)s" in sql

    plain = str(pending_events_statement(1, for_update=False).compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" not in plain


@pytest.mark.asyncio
async def test_create_pending_defaults_attempt_count_zero(db_session):
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository

    repo = CandidateEventRepository(db_session)
    await repo.create_pending(_pending_data("pending:attempts"))
    await db_session.commit()

    events = await repo.claim_next_pending()
    assert len(events) == 1
    assert events[0].attempt_count == 0


@pytest.mark.asyncio
async def test_set_status_updates_attempt_count(db_session):
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository

    repo = CandidateEventRepository(db_session)
    await repo.create_pending(_pending_data("pending:attempts:set"))
    await db_session.commit()

    claimed = await repo.claim_next_pending()
    await repo.set_status(claimed[0].id, "pending", attempt_count=2)
    await db_session.commit()

    event = await repo.get(claimed[0].id)
    assert event is not None
    assert event.attempt_count == 2


@pytest.mark.asyncio
async def test_set_status_stamps_updated_at(db_session):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update
    from whaledecode.adapters.db.models.candidate_event import CandidateEventModel
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository

    repo = CandidateEventRepository(db_session)
    await repo.create_pending(_pending_data("pending:touch"))
    await db_session.commit()
    claimed = await repo.claim_next_pending()

    await db_session.execute(
        update(CandidateEventModel)
        .where(CandidateEventModel.id == claimed[0].id)
        .values(updated_at=datetime.now(UTC) - timedelta(minutes=30))
    )
    await db_session.commit()

    await repo.set_status(claimed[0].id, "processing")
    await db_session.commit()

    event = await repo.get(claimed[0].id)
    assert event is not None
    assert event.updated_at is not None
    assert event.updated_at > datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)


@pytest.mark.asyncio
async def test_record_failure_routes_to_pending_then_dead_letter(db_session):
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository

    repo = CandidateEventRepository(db_session)
    await repo.create_pending(_pending_data("pending:dlq"))
    await db_session.commit()
    claimed = await repo.claim_next_pending()

    status = await repo.record_failure(claimed[0].id, max_attempts=3)
    await db_session.commit()
    event = await repo.get(claimed[0].id)
    assert status == "pending"
    assert event is not None and event.attempt_count == 1

    status = await repo.record_failure(claimed[0].id, max_attempts=3)
    await db_session.commit()
    event = await repo.get(claimed[0].id)
    assert status == "pending"
    assert event is not None and event.attempt_count == 2

    status = await repo.record_failure(claimed[0].id, max_attempts=3)
    await db_session.commit()
    event = await repo.get(claimed[0].id)
    assert status == "dead_letter"
    assert event is not None and event.attempt_count == 3


@pytest.mark.asyncio
async def test_reap_zombie_events_resets_stale_processing(db_session):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select, update
    from whaledecode.adapters.db.models.candidate_event import CandidateEventModel
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository

    repo = CandidateEventRepository(db_session)
    await repo.create_pending(_pending_data("reap:stale"))
    await db_session.commit()
    claimed = await repo.claim_next_pending()
    await repo.set_status(claimed[0].id, "processing")
    await db_session.commit()

    await db_session.execute(
        update(CandidateEventModel)
        .where(CandidateEventModel.id == claimed[0].id)
        .values(updated_at=datetime.now(UTC) - timedelta(minutes=15))
    )
    await db_session.commit()

    reaped = await repo.reap_zombie_events(minutes=10)
    await db_session.commit()

    assert reaped == 1
    row = await db_session.execute(
        select(CandidateEventModel).where(CandidateEventModel.id == claimed[0].id)
    )
    assert row.scalar_one().status == "pending"


@pytest.mark.asyncio
async def test_reap_zombie_events_keeps_fresh_processing(db_session):
    from sqlalchemy import select
    from whaledecode.adapters.db.models.candidate_event import CandidateEventModel
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository

    repo = CandidateEventRepository(db_session)
    await repo.create_pending(_pending_data("reap:fresh"))
    await db_session.commit()
    claimed = await repo.claim_next_pending()
    await repo.set_status(claimed[0].id, "processing")
    await db_session.commit()

    reaped = await repo.reap_zombie_events(minutes=10)
    await db_session.commit()

    assert reaped == 0
    row = await db_session.execute(
        select(CandidateEventModel).where(CandidateEventModel.id == claimed[0].id)
    )
    assert row.scalar_one().status == "processing"
