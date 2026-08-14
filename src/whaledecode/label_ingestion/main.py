"""Orchestration + CLI for the EVM address-label ingestion pipeline.

Usage
-----
    # Live crawl (needs GITHUB_TOKEN in env for higher quota):
    python -m whaledecode.label_ingestion.main --db evm_labels.db

    # Override which repos to crawl:
    python -m whaledecode.label_ingestion.main --repos duneanalytics/spellbook

    # Offline self-check (no network / no token required):
    python -m whaledecode.label_ingestion.main --demo
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field

from whaledecode.label_ingestion.config import DEFAULT_REPO_TARGETS, LABEL_FILE_SUFFIXES, RepoTarget
from whaledecode.label_ingestion.github_client import GitHubClient
from whaledecode.label_ingestion.normalizer import flag_cross_chain, normalize
from whaledecode.label_ingestion.parsers import extract_records
from whaledecode.label_ingestion.storage import LabelStore
from whaledecode.label_ingestion.token_metadata import TokenMetadataService

logger = logging.getLogger("evm_label_pipeline")


@dataclass
class RunStats:
    files: int = 0
    records: int = 0
    normalized: int = 0
    stored: int = 0
    skipped: int = 0
    by_repo: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)


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


async def run(
    targets: list[RepoTarget], db_path: str, token: str | None, rpc_urls: dict[int, str] | None = None
) -> RunStats:
    stats = RunStats()
    store = LabelStore(db_path)
    try:
        async with GitHubClient(token) as client:
            for target in targets:
                try:
                    await ingest_repo(client, store, target, stats)
                except Exception as exc:  # noqa: BLE001 - one repo failing must not abort the run
                    msg = f"{target.full_name}: {exc}"
                    logger.error(f"repo_failed {msg}")
                    stats.failures.append(msg)
        # Token metadata (Uniswap + CoinGecko lists). On-chain RPC Multicall is a
        # per-address fallback inside TokenMetadataService.resolve(), not run here.
        try:
            svc = TokenMetadataService(rpc_urls or {})
            meta_labels = await svc.load_lists()
            if meta_labels:
                written = store.upsert(meta_labels)
                stats.stored += written
                stats.normalized += len(meta_labels)
                stats.by_repo["token-metadata"] = stats.by_repo.get("token-metadata", 0) + written
        except Exception as exc:  # noqa: BLE001 - token lists are best-effort
            msg = f"token-metadata: {exc}"
            logger.error(f"token_metadata_failed {msg}")
            stats.failures.append(msg)
    finally:
        store.close()
    return stats


def _demo(db_path: str) -> RunStats:
    """Offline end-to-end self-check using embedded sample data (no network)."""
    etherscan_json = """[
      {"address":"0x28c6c06298d514db089934071355e5743bf21d60","name":"Binance: Hot Wallet 6","category":"CEX","chainId":1},
      {"address":"0x742d35cc6634c0532925a3b844bc454e4438f44e","name":"Binance: Cold Wallet 1","category":"CEX","chainId":1},
      {"address":"0xbad","name":"Bad Row","category":"CEX","chainId":1}
    ]"""
    spellbook_sql = (
        "INSERT INTO labels (address, name, category) VALUES\n"
        "('0x3f5ce5fbfe3e9af3971dd833d26ba9b5c936f0be', 'Binance', 'CEX'),\n"
        "('0x1111111254eeb25477b68fb85ed929f73a960582', '1inch Router', 'DEX');\n"
    )
    token_list_json = json.dumps(
        {
            "tokens": [
                {"chainId": 1, "address": "0xdac17f958d2ee523a2206206994597c13d831ec7", "name": "Tether USD", "symbol": "USDT", "decimals": 6},
                {"chainId": 42161, "address": "0xaf88d065e9586a8b6c0d8f1c3b5c0deadbeef00", "name": "USD Coin", "symbol": "USDC", "decimals": 6},
            ]
        }
    )

    store = LabelStore(db_path)
    stats = RunStats()
    samples = [
        ("brianleect/etherscan-labels", "combined/combinedAllLabels.json", etherscan_json),
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
    # Token metadata (offline parse of a sample token list)
    svc = TokenMetadataService()
    meta = svc.parse_token_list(token_list_json, source="demo")
    if meta:
        store.upsert(meta)
        stats.stored += len(meta)
        stats.normalized += len(meta)
        stats.by_repo["token-metadata"] = stats.by_repo.get("token-metadata", 0) + len(meta)
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
            "failures": stats.failures,
        },
    )
    sys.stdout.write(
        f"\nSummary: files={stats.files} records={stats.records} "
        f"normalized={stats.normalized} stored={stats.stored} skipped={stats.skipped}\n"
    )
    for repo, n in stats.by_repo.items():
        sys.stdout.write(f"  {repo}: {n} labels\n")
    if stats.failures:
        sys.stdout.write(f"\n{len(stats.failures)} source(s) failed:\n")
        for f in stats.failures:
            sys.stdout.write(f"  ! {f}\n")


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
