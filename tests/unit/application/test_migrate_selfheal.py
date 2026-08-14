from unittest.mock import patch

import alembic.command

from whaledecode.main import _run_migrations


class _FakeSettings:
    ENV = "dev"
    DATABASE_URL = "postgresql://u:p@localhost/db"


def test_run_migrations_normal_path_does_not_stamp():
    with patch.object(alembic.command, "upgrade") as upgrade, patch.object(
        alembic.command, "stamp"
    ) as stamp:
        _run_migrations(_FakeSettings())
    assert upgrade.called
    assert not stamp.called


def test_run_migrations_self_heals_orphan_revision():
    calls = {"upgrade": 0}

    def fake_upgrade(cfg, rev):
        calls["upgrade"] += 1
        if calls["upgrade"] == 1:
            raise Exception("Can't locate revision identified by 'deadbeef'")

    with patch.object(alembic.command, "upgrade", side_effect=fake_upgrade), patch.object(
        alembic.command, "stamp"
    ) as stamp:
        _run_migrations(_FakeSettings())

    assert stamp.called
    assert calls["upgrade"] == 2


def test_run_migrations_propagates_unrelated_errors():
    with patch.object(
        alembic.command,
        "upgrade",
        side_effect=RuntimeError("connection refused"),
    ), patch.object(alembic.command, "stamp") as stamp:
        try:
            _run_migrations(_FakeSettings())
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected RuntimeError to propagate")
    assert not stamp.called
