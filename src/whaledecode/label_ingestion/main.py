"""Orchestration + CLI for the EVM address-label ingestion pipeline.

Usage
-----
    # Live crawl (needs GITHUB_TOKEN in env for higher quota):
    python -m evm_label_pipeline.main --db evm_labels.db

    # Override which repos to crawl:
    python -m evm_label_pipeline.main --repos DefiLlama/token-lists,duneanalytics/spellbook

    # Offline self-check (no network / no token required):
    python -m evm_label_pipeline.main --demo
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field

from whaledecode.label_ingestion.config import DEFAULT_REPO_TARGETS, LABEL_FILE_SUFFIXES, RepoTarget
from whaledecode.label_ingestion.github_client import GitHubClient
from whaledecode.label_ingestion.normalizer import flag_cross_chain, normalize
from whaledecode.label_ingestion.parsers import extract_records
from whaledecode.label_ingestion.storage import LabelStore

logger = logging.getLogger("evm_label_pipeline")


@dataclass
class RunStats:
    files: int = 0
    records: int = 0
    normalized: int = 0
    stored: int = 0
    skipped: int = 0
    by_repo: dict[str, int] = field(default_factory=dict)


async def ingest_repo(client: GitHubClient, store: LabelStore, target: RepoTarget, stats: RunStats) -> None:
    source_repo = target.full_name
    async for path, text in client.iter_label_files(
        source_repo, target.ref, LABEL_FILE_SUFFIXES, target.path_includes
    ):
        stats.files += 1
        source = f"github:{source_repo}:{path}"
        pending = []
        for raw in extract_records(text, path, source=source_repo):
            stats.records += 1
            label = normalize(raw, source)
            if label is None:
                stats.skipped += 1
                continue
            pending.extend(flag_cross_chain(label))
        if pending:
            written = store.upsert(pending)
            stats.stored += written
            stats.normalized += len(pending)
            stats.by_repo[source_repo] = stats.by_repo.get(source_repo, 0) + written
        logger.info("repo_file_done", extra={"repo": source_repo, "path": path, "labels": len(pending)})


async def run(targets: list[RepoTarget], db_path: str, token: str | None) -> RunStats:
    stats = RunStats()
    store = LabelStore(db_path)
    try:
        async with GitHubClient(token) as client:
            for target in targets:
                try:
                    await ingest_repo(client, store, target, stats)
                except Exception as exc:  # noqa: BLE001 - one repo failing must not abort the run
                    logger.error("repo_failed", extra={"repo": target.full_name, "error": str(exc)})
    finally:
        store.close()
    return stats


def _demo(db_path: str) -> RunStats:
    """Offline end-to-end self-check using embedded sample data (no network)."""
    token_list_json = """[
      {"address":"0x28c6c06298d514db089934071355e5743bf21d60","chainId":1,"name":"Binance: Hot Wallet 6","symbol":"ETH"},
      {"address":"0x7a250d5630b4cf539739df2c5dacb4c659f2488d","chainId":1,"name":"Uniswap V2: Router 2","symbol":"UNI"},
      {"address":"0xdac17f958d2ee523a2206206994597c13d831ec7","chainId":1,"name":"Tether USD","symbol":"USDT"}
    ]"""
    arkham_csv = (
        "address,name,category,chain\n"
        "0x742d35cc6634c0532925a3b844bc454e4438f44e,Binance: Cold Wallet 1,CEX,1\n"
        "0xnotanaddress,Bad Row,CEX,1\n"  # invalid -> discarded by normalizer
    )
    spellbook_sql = (
        "INSERT INTO labels (address, name, category) VALUES\\n"
        "('0x3f5ce5fbfe3e9af3971dd833d26ba9b5c936f0be', 'Binance', 'CEX'),\\n"
        "('0x1111111254eeb25477b68fb85ed929f73a960582', '1inch Router', 'DEX');\\n"
    )

    store = LabelStore(db_path)
    stats = RunStats()
    samples = [
        ("DefiLlama/token-lists", "tokenlists/sample.json", token_list_json),
        ("brianmcmichael/arkham-intelligence-data", "wallets.csv", arkham_csv),
        ("duneanalytics/spellbook", "labels/binance.sql", spellbook_sql),
    ]
    for repo, path, text in samples:
        stats.files += 1
        for raw in extract_records(text, path, source=repo):
            stats.records += 1
            label = normalize(raw, f"github:{repo}:{path}")
            if label is None:
                stats.skipped += 1
                continue
            pending = flag_cross_chain(label)
            store.upsert(pending)
            stats.stored += len(pending)
            stats.normalized += len(pending)
            stats.by_repo[repo] = stats.by_repo.get(repo, 0) + len(pending)
    store.close()
    return stats


def _print_summary(stats: RunStats) -> None:
    logger.info(
        "ingest_summary",
        extra={
            "files": stats.files,
            "records": stats.records,
            "normalized": stats.normalized,
            "stored": stats.stored,
            "skipped": stats.skipped,
            "by_repo": stats.by_repo,
        },
    )
    sys.stdout.write(
        f"\nSummary: files={stats.files} records={stats.records} "
        f"normalized={stats.normalized} stored={stats.stored} skipped={stats.skipped}\n"
    )
    for repo, n in stats.by_repo.items():
        sys.stdout.write(f"  {repo}: {n} labels\n")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="Ingest public EVM address labels from GitHub.")
    parser.add_argument("--db", default="evm_labels.db", help="SQLite DB path")
    parser.add_argument("--repos", default=None, help="Comma-separated owner/repo overrides")
    parser.add_argument("--token", default=None, help="GitHub PAT (else GITHUB_TOKEN env)")
    parser.add_argument("--demo", action="store_true", help="Offline self-check, no network")
    args = parser.parse_args(argv)

    if args.demo:
        stats = _demo(args.db)
        _print_summary(stats)
        return 0

    if args.repos:
        targets = [RepoTarget(r.strip()) for r in args.repos.split(",") if r.strip()]
    else:
        targets = list(DEFAULT_REPO_TARGETS)

    stats = asyncio.run(run(targets, args.db, args.token))
    _print_summary(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
