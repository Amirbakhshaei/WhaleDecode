# Fix: `curated_wallets` migration never applied to production

## Root cause
- `alembic.ini` → `script_location = alembic`. Real chain: `0001_initial` → … → `0008_nullable_raw_json` (head), all in `alembic/versions/`. Dockerfile only copies `alembic/` + `alembic.ini`.
- The new migration was wrongly placed in `migrations/versions/0001_curated_wallets_solana.py` — a directory Alembic never reads and the image never receives. `whaledecode migrate` (Railway release command) ran `upgrade head` on `alembic/versions/`, saw `0008` applied, did nothing.
- The misplaced migration was also incorrect: `down_revision = None` (would clash with `0001` as a second root) and it called `drop_constraint("uq_address_chain", …)` — but the original `curated_wallets` has **no** such constraint (only PK + non-unique `ix_curated_wallets_address`).
- Result: production `alembic_version` = `0008`; `curated_wallets` lacks `network_family`/`category`/timestamps → live webhook (`webhook.py:204`) and sync CLI crash on `UndefinedColumnError`.

## Changes
1. **Create `alembic/versions/0009_curated_wallets_solana.py`** (revision `0009`, down_revision `0008`). ALTER address `VARCHAR(42)`→`VARCHAR(64)`; ALTER chain `VARCHAR(20)`→`VARCHAR(16)`; ADD `network_family VARCHAR(8) NOT NULL DEFAULT 'EVM'`, `category VARCHAR(64) NOT NULL DEFAULT 'Smart Money'`, `created_at`/`updated_at TIMESTAMPTZ DEFAULT now(); then `create_unique_constraint("uq_curated_address_chain", ["address","chain"])` — **no drop** (constraint never existed). Drop the backfill server defaults. `downgrade()` reverses in order (drop constraint, drop columns, revert types).
2. **Delete `migrations/` directory** (dead, never used).
3. **Revert the speculative `_run_migrations` self-heal** in `src/whaledecode/main.py` back to the simple `migrate` command, and **delete `tests/unit/application/test_migrate_selfheal.py`** (unrelated to the real cause).

## Corrected migration (0009)
```python
"""curated_wallets: Solana-ready + richer metadata.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-14
"""
from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "curated_wallets", "address",
        existing_type=sa.String(42), type_=sa.String(64), nullable=False,
    )
    op.alter_column(
        "curated_wallets", "chain",
        existing_type=sa.String(20), type_=sa.String(16), nullable=False,
    )
    op.add_column(
        "curated_wallets",
        sa.Column("network_family", sa.String(8), nullable=False, server_default="EVM"),
    )
    op.add_column(
        "curated_wallets",
        sa.Column("category", sa.String(64), nullable=False, server_default="Smart Money"),
    )
    op.add_column(
        "curated_wallets",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.add_column(
        "curated_wallets",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_curated_address_chain", "curated_wallets", ["address", "chain"])
    op.execute("ALTER TABLE curated_wallets ALTER COLUMN network_family DROP DEFAULT")
    op.execute("ALTER TABLE curated_wallets ALTER COLUMN category DROP DEFAULT")


def downgrade():
    op.drop_constraint("uq_curated_address_chain", "curated_wallets", type_="unique")
    op.drop_column("curated_wallets", "updated_at")
    op.drop_column("curated_wallets", "created_at")
    op.drop_column("curated_wallets", "category")
    op.drop_column("curated_wallets", "network_family")
    op.alter_column(
        "curated_wallets", "chain",
        existing_type=sa.String(16), type_=sa.String(20), nullable=False,
    )
    op.alter_column(
        "curated_wallets", "address",
        existing_type=sa.String(64), type_=sa.String(42), nullable=False,
    )
```

## Apply (user chose: commit & redeploy)
- Commit the above. Railway release command `whaledecode migrate` runs `alembic upgrade head` → applies `0009` (container already has the new model code). No code-logic redeploy strictly required, but the migration file must be in the image (it will be after commit/deploy).

## Verify
- `python -m whaledecode.cli.sync_curated_entities` → no `UndefinedColumnError`.
- Alchemy webhook POST → `list_active(chain=ETH)` succeeds (no `UndefinedColumnError` in logs).
- `alembic heads` → single head `0009`.
- `ruff check` + `pytest tests/unit/application/test_curation_sources.py` pass.

## Risk
- `CREATE UNIQUE INDEX` fails if `curated_wallets` has duplicate `(address, chain)` rows. Pre-check before deploy:
  `SELECT address, chain, count(*) FROM curated_wallets GROUP BY 1,2 HAVING count(*) > 1;`
  Dedupe if any rows return.
