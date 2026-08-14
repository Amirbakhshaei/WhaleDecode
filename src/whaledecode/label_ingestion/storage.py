"""SQLite storage with upsert (conflict on (address, chain_id)) + lookup indexes."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from typing import Any

from web3 import Web3
from whaledecode.label_ingestion.normalizer import AddressLabel


class LabelStore:
    """Thin, typed SQLite wrapper for EVM address labels."""

    def __init__(self, path: str = "evm_labels.db") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS address_labels (
                address         TEXT    NOT NULL,
                chain_id        INTEGER NOT NULL,
                name_tag        TEXT    NOT NULL,
                entity          TEXT    DEFAULT '',
                category        TEXT    DEFAULT 'Unknown',
                source          TEXT    DEFAULT '',
                confidence_score REAL   DEFAULT 0.5,
                updated_at      TEXT    NOT NULL,
                PRIMARY KEY (address, chain_id)
            );
            CREATE INDEX IF NOT EXISTS idx_labels_address        ON address_labels(address);
            CREATE INDEX IF NOT EXISTS idx_labels_chain_category ON address_labels(chain_id, category);
            """
        )
        self._conn.commit()

    def upsert(self, labels: Iterable[AddressLabel]) -> int:
        """Insert/update labels; on conflict keep the higher confidence_score + latest source.

        Returns the number of rows written.
        """
        rows: list[tuple[Any, ...]] = []
        for lbl in labels:
            rows.append(
                (
                    lbl.address,
                    lbl.chain_id,
                    lbl.name_tag,
                    lbl.entity,
                    lbl.category,
                    lbl.source,
                    lbl.confidence_score,
                    lbl.updated_at,
                )
            )
        if not rows:
            return 0
        self._conn.executemany(
            """
            INSERT INTO address_labels
                (address, chain_id, name_tag, entity, category, source, confidence_score, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(address, chain_id) DO UPDATE SET
                name_tag         = excluded.name_tag,
                entity           = excluded.entity,
                category         = excluded.category,
                source           = excluded.source,
                confidence_score = MAX(confidence_score, excluded.confidence_score),
                updated_at       = excluded.updated_at
            WHERE excluded.confidence_score >= confidence_score
               OR excluded.updated_at > updated_at;
            """,
            rows,
        )
        self._conn.commit()
        return len(rows)

    def query(self, address: str, chain_id: int | None = None) -> list[AddressLabel]:
        # Stored addresses are EIP-55 checksummed; normalize the lookup to match.
        lookup = address
        try:
            lookup = Web3.to_checksum_address(address)
        except Exception:  # noqa: BLE001 - fall back to raw form if not checksummable
            pass
        sql = "SELECT * FROM address_labels WHERE address = ?"
        params: list[Any] = [lookup]
        if chain_id is not None:
            sql += " AND chain_id = ?"
            params.append(chain_id)
        cur = self._conn.execute(sql, params)
        return [_row_to_label(r) for r in cur.fetchall()]

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM address_labels").fetchone()[0])

    def stats_by_category(self) -> list[tuple[str, int]]:
        cur = self._conn.execute(
            "SELECT category, COUNT(*) AS n FROM address_labels GROUP BY category ORDER BY n DESC"
        )
        return [(r["category"], r["n"]) for r in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()


def _row_to_label(row: sqlite3.Row) -> AddressLabel:
    return AddressLabel(
        address=row["address"],
        chain_id=row["chain_id"],
        name_tag=row["name_tag"],
        entity=row["entity"],
        category=row["category"],
        source=row["source"],
        confidence_score=row["confidence_score"],
        updated_at=row["updated_at"],
    )
