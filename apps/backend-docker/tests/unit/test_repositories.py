import pytest
from sqlalchemy import select
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
async def test_claim_quarantines_poison_pill_and_keeps_valid_rows(db_session):
    from whaledecode.adapters.db.models.candidate_event import CandidateEventModel
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository

    repo = CandidateEventRepository(db_session)
    await repo.create_pending(_pending_data("pending:good"))
    # Truncated EVM hash — would crash Hash() validation during hydration.
    await repo.create_pending({**_pending_data("pending:bad"), "tx_hash": "0x" + "a" * 10})
    await db_session.commit()

    events = await repo.claim_next_pending(limit=10)
    assert [e.dedupe_key for e in events] == ["pending:good"]

    bad_row = (
        await db_session.execute(
            select(CandidateEventModel).where(CandidateEventModel.dedupe_key == "pending:bad")
        )
    ).scalar_one()
    assert bad_row.status == "FAILED_HYDRATION"
    assert bad_row.error_message and "Hydration error" in bad_row.error_message


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


@pytest.mark.asyncio
async def test_set_status_completed_strips_raw_json(db_session):
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository

    repo = CandidateEventRepository(db_session)
    await repo.create_pending(_pending_data("pending:strip"))
    await db_session.commit()

    claimed = await repo.claim_next_pending()
    await repo.set_status(claimed[0].id, "completed")
    await db_session.commit()

    row = await repo.get(claimed[0].id)
    assert row is not None
    assert row.status == "completed"
    assert row.raw_json == {}


@pytest.mark.asyncio
async def test_purge_stale_events_deletes_old_terminal_rows(db_session):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import text

    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository

    repo = CandidateEventRepository(db_session)
    for i, dedupe in enumerate(("purge:old:skipped", "purge:old:completed", "purge:fresh")):
        await repo.create_pending(_pending_data(dedupe))
    await db_session.commit()

    # Age the first two rows and mark them terminal.
    cutoff = datetime.now(UTC) - timedelta(days=10)
    await db_session.execute(
        text("UPDATE candidate_events SET status = 'skipped', created_at = :cutoff WHERE dedupe_key = 'purge:old:skipped'"),
        {"cutoff": cutoff},
    )
    await db_session.execute(
        text("UPDATE candidate_events SET status = 'completed', created_at = :cutoff WHERE dedupe_key = 'purge:old:completed'"),
        {"cutoff": cutoff},
    )
    await db_session.commit()

    purged = await repo.purge_stale_events()
    await db_session.commit()
    assert purged == 2

    remaining = await repo.claim_next_pending(limit=10)
    assert [e.dedupe_key for e in remaining] == ["purge:fresh"]


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
async def test_update_existing_row_no_missing_greenlet(db_session):
    """update() must not trigger a synchronous refresh (MissingGreenlet) after flush."""
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository

    repo = CandidateEventRepository(db_session)
    await repo.create_pending(_pending_data("pending:update"))
    await db_session.commit()

    event = await repo.get_by_dedupe_key("pending:update")
    assert event is not None
    event.score = 90.0
    event.status = "completed"
    event.raw_json = {"value_usd": 2_000_000.0}

    updated = await repo.update(event)
    assert updated.id == event.id
    assert updated.score == 90.0
    assert updated.status == "completed"
    assert updated.updated_at is not None

    await db_session.commit()
    persisted = await repo.get(event.id)
    assert persisted is not None and persisted.score == 90.0


@pytest.mark.asyncio
async def test_update_inserts_when_dedupe_missing(db_session):
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository
    from whaledecode.domain.entities.candidate_event import CandidateEvent
    from whaledecode.domain.value_objects.hash import Hash

    repo = CandidateEventRepository(db_session)
    event = CandidateEvent(
        wallet_id=1,
        chain="ETH",
        tx_hash=Hash("0x" + "b" * 64),
        log_index=0,
        block_number=100,
        event_type="TRANSFER",
        raw_json={"value_usd": 100.0},
        score=80.0,
        dedupe_key="pending:update:new",
    )
    created = await repo.update(event)
    assert created.id is not None
    assert created.score == 80.0


@pytest.mark.asyncio
async def test_requeue_stuck_events_resets_dead_letter_and_skipped(db_session):
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository

    repo = CandidateEventRepository(db_session)
    for key, status in [("stuck:dlq", "dead_letter"), ("stuck:skip", "skipped")]:
        data = _pending_data(key)
        data["score"] = 0.0  # pre-fix ingest bug
        data["raw_json"] = {"value_usd": 1_000_000.0}
        await repo.create_pending(data)
        await db_session.commit()
        claimed = await repo.claim_next_pending()
        await repo.set_status(claimed[0].id, status)
        await db_session.commit()

    requeued = await repo.requeue_stuck_events()
    await db_session.commit()
    assert requeued == 2

    events = await repo.claim_next_pending(limit=10)
    assert len(events) == 2
    assert all(e.status == "pending" for e in events)
    assert all(e.attempt_count == 0 for e in events)
    assert all(e.score > 0 for e in events)  # score recomputed, not 0.0


@pytest.mark.asyncio
async def test_requeue_stuck_events_noop_when_none_stuck(db_session):
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository

    repo = CandidateEventRepository(db_session)
    await repo.create_pending(_pending_data("stuck:none"))
    await db_session.commit()

    assert await repo.requeue_stuck_events() == 0


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
async def test_claim_next_pending_excludes_dead_letter_events(db_session):
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository

    repo = CandidateEventRepository(db_session)
    await repo.create_pending(_pending_data("dlq:poison"))
    await db_session.commit()
    claimed = await repo.claim_next_pending()
    await repo.record_failure(claimed[0].id, max_attempts=1)
    await db_session.commit()

    await repo.create_pending(_pending_data("dlq:healthy"))
    await db_session.commit()

    polled = await repo.claim_next_pending(limit=10)
    assert [e.dedupe_key for e in polled] == ["dlq:healthy"]


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


@pytest.mark.asyncio
async def test_requeue_recent_events_resets_pending_and_recomputes_score(db_session):
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository

    repo = CandidateEventRepository(db_session)
    data = _pending_data("recent:vip")
    data["raw_json"] = {"value_usd": 1_000_000.0}
    data["score"] = 0.0
    await repo.create_pending(data)
    await db_session.commit()
    claimed = await repo.claim_next_pending()
    await repo.set_status(claimed[0].id, "completed")
    await repo.set_status(claimed[0].id, "dead_letter", attempt_count=3)
    await db_session.commit()

    requeued = await repo.requeue_recent_events(hours=24)
    await db_session.commit()
    assert requeued == 1

    events = await repo.claim_next_pending(limit=10)
    assert len(events) == 1
    assert events[0].status == "pending"
    assert events[0].attempt_count == 0
    assert events[0].score > 0


@pytest.mark.asyncio
async def test_requeue_recent_events_skips_older_rows(db_session):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from whaledecode.adapters.db.models.candidate_event import CandidateEventModel
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository

    repo = CandidateEventRepository(db_session)
    await repo.create_pending(_pending_data("recent:old"))
    await db_session.commit()
    await db_session.execute(
        update(CandidateEventModel)
        .where(CandidateEventModel.dedupe_key == "recent:old")
        .values(created_at=datetime.now(UTC) - timedelta(days=3), status="pending")
    )
    await db_session.commit()

    assert await repo.requeue_recent_events(hours=24) == 0


@pytest.mark.asyncio
async def test_requeue_recent_events_noop_when_none(db_session):
    from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository

    repo = CandidateEventRepository(db_session)
    assert await repo.requeue_recent_events(hours=24) == 0


@pytest.mark.asyncio
async def test_alert_purge_pending_deletes_only_pending(db_session):
    from whaledecode.adapters.db.repositories.alert import AlertRepository
    from whaledecode.domain.entities.alert import Alert

    repo = AlertRepository(db_session)
    await repo.create(Alert(user_id=1, event_id=1, status="pending", dedupe_key="alert:new"))
    await repo.create(Alert(user_id=1, event_id=2, status="sent", dedupe_key="alert:sent"))
    await db_session.commit()

    purged = await repo.purge_pending()
    await db_session.commit()
    assert purged == 1

    remaining = await repo.list_by_status("sent")
    assert [a.dedupe_key for a in remaining] == ["alert:sent"]
    assert len(await repo.list_by_status("pending")) == 0


def test_curated_wallet_entity_has_category():
    """Regression guard: webhook telemetry logs wallet.category, so the domain
    entity must expose it (otherwise _process_webhook_payload raises
    AttributeError on every matched wallet)."""
    from whaledecode.adapters.db.repositories.curated_wallet import CuratedWalletRepository

    wallet = CuratedWallet(address="0xabc", chain=Chain.ETH)
    assert wallet.category == "Unknown"
    assert getattr(wallet, "category", "Unknown") == "Unknown"

    class _FakeModel:
        id = 1
        address = "0xABC"
        chain = "ETH"
        label = "whale"
        tags = "a,b"
        quality_score = 90.0
        category = "Smart Money"
        is_active = True
        is_monitored_active = True
        tx_count_30d = 5
        last_activity_at = None
        velocity_penalty = 1.0

    dom = CuratedWalletRepository._to_domain(None, _FakeModel())
    assert dom.category == "Smart Money"
