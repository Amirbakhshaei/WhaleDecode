"""Verify the daily EVM-label cron wiring in the worker (no network)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from click.testing import CliRunner
from whaledecode import main as cli_main
from whaledecode.config.settings import Settings
from whaledecode.entrypoints import worker


def test_ingest_labels_runs_without_postgres_env(tmp_path, monkeypatch) -> None:
    """Label ingestion must NOT require DATABASE_URL / BOT_TOKEN / GROQ_API_KEY."""
    import whaledecode.label_ingestion.main as lim

    async def fake_run(targets, db_path, token, rpc_urls=None):
        return SimpleNamespace(files=1, records=1, stored=1, skipped=0, failures=[], by_repo={})

    monkeypatch.setattr(lim, "run", fake_run)
    monkeypatch.setattr(cli_main, "setup_logging", lambda s: None)
    for var in ("DATABASE_URL", "BOT_TOKEN", "GROQ_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    result = CliRunner().invoke(
        cli_main.cli, ["ingest-labels", "--db", str(tmp_path / "labels.db")]
    )
    assert result.exit_code == 0, result.output
    assert "Ingested:" in result.output


def test_ingest_evm_labels_invokes_run_with_settings(tmp_path, monkeypatch) -> None:
    settings = Settings()
    settings.GITHUB_TOKEN = None
    settings.LABELS_DB_PATH = str(tmp_path / "labels.db")

    captured: dict = {}

    async def fake_run(targets, db_path, token, rpc_urls=None):
        captured.update(targets=targets, db_path=db_path, token=token, rpc_urls=rpc_urls)
        return SimpleNamespace(files=2, records=2, stored=2, skipped=0)

    import whaledecode.label_ingestion.main as lim

    monkeypatch.setattr(lim, "run", fake_run)

    asyncio.run(worker._ingest_evm_labels(settings))

    assert captured["db_path"] == settings.LABELS_DB_PATH
    assert captured["token"] is None
    assert len(captured["targets"]) >= 1


def test_ingest_evm_labels_swallows_github_errors(tmp_path, monkeypatch) -> None:
    settings = Settings()
    settings.LABELS_DB_PATH = str(tmp_path / "labels.db")

    async def boom(targets, db_path, token, rpc_urls=None):
        raise RuntimeError("github down")

    import whaledecode.label_ingestion.main as lim

    monkeypatch.setattr(lim, "run", boom)

    # Must not propagate: a GitHub outage must not kill the worker scheduler.
    asyncio.run(worker._ingest_evm_labels(settings))
