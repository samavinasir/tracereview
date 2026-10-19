import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from auditable_research import api, storage


class _FakeSession:
    def __init__(self, rowcount: int) -> None:
        self.statements: list = []
        self._rowcount = rowcount

    async def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(rowcount=self._rowcount)


class _FakeBegin:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest.mark.asyncio
async def test_fail_interrupted_runs_only_targets_unfinished_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession(rowcount=3)
    monkeypatch.setattr(storage, "Session", SimpleNamespace(begin=lambda: _FakeBegin(session)))

    changed = await storage.fail_interrupted_runs()

    assert changed == 3
    (statement,) = session.statements
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert sql.startswith("UPDATE research_runs SET")
    assert "status=%(status)s" in sql and "error=%(error)s" in sql
    assert "research_runs.status IN" in sql
    params = statement.compile(dialect=postgresql.dialect()).params
    assert params["status"] == "failed"
    assert params["error"] == storage.INTERRUPTED_RUN_ERROR
    # Only queued/running rows are selected; completed/failed ones are never touched.
    in_lists = [value for key, value in params.items() if key.startswith("status_")]
    assert in_lists == [["queued", "running"]]
    # updated_at is refreshed too, so the UI shows when the run was failed.
    assert "updated_at" in params


@pytest.mark.asyncio
async def test_app_startup_fails_interrupted_runs_after_storage_init(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []

    async def init() -> None:
        order.append("init")

    async def fail() -> int:
        order.append("fail")
        return 2

    monkeypatch.setattr(api, "initialize_storage", init)
    monkeypatch.setattr(api, "fail_interrupted_runs", fail)
    monkeypatch.setattr(api, "engine", SimpleNamespace(dispose=AsyncMock()))

    async with api.lifespan(api.app):
        assert order == ["init", "fail"]


async def _database_reachable() -> bool:
    try:
        async with storage.engine.connect():
            return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_fail_interrupted_runs_against_real_postgres() -> None:
    """Runs only when DATABASE_URL points at a reachable Postgres."""
    try:
        reachable = await asyncio.wait_for(_database_reachable(), timeout=3)
    except TimeoutError:
        reachable = False
    if not reachable:
        await storage.engine.dispose()
        pytest.skip("No reachable Postgres for DATABASE_URL")
    try:
        await storage.initialize_storage()
        ids = {}
        for status in ("queued", "running", "completed", "failed"):
            run_id = await storage.create_research(f"Question for a {status} run with padding")
            await storage.save_run(run_id, f"Question for a {status} run with padding", {}, status, error="original" if status == "failed" else None)
            ids[status] = run_id

        await storage.fail_interrupted_runs()

        states = {status: await storage.get_status(run_id) for status, run_id in ids.items()}
        assert states["queued"]["status"] == "failed"
        assert states["running"]["status"] == "failed"
        assert states["queued"]["error"] == storage.INTERRUPTED_RUN_ERROR
        assert states["completed"]["status"] == "completed" and states["completed"]["error"] is None
        assert states["failed"]["error"] == "original"
    finally:
        await storage.engine.dispose()
