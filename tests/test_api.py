from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest

from auditable_research import api


@pytest.mark.asyncio
async def test_research_endpoint_validates_input_and_queues_run(monkeypatch: pytest.MonkeyPatch) -> None:
    api._request_times.clear()
    research_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    create_research = AsyncMock(return_value=research_id)
    workflow = AsyncMock()
    monkeypatch.setattr(api, "create_research", create_research)
    monkeypatch.setattr(api, "_run_workflow", workflow)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
        invalid = await client.post("/research", json={"question": "short"})
        valid = await client.post("/research", json={"question": "What evidence supports this mechanism?"})

    assert invalid.status_code == 422
    assert valid.status_code == 202
    assert valid.json()["research_id"] == str(research_id)
    create_research.assert_awaited_once_with("What evidence supports this mechanism?")
    workflow.assert_awaited_once()


@pytest.mark.asyncio
async def test_research_endpoint_rate_limits_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    api._request_times.clear()
    old_limit = api.settings.research_rate_limit_requests
    api.settings.research_rate_limit_requests = 1
    monkeypatch.setattr(api, "create_research", AsyncMock(return_value=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")))
    monkeypatch.setattr(api, "_run_workflow", AsyncMock())
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
            body = {"question": "What evidence supports this mechanism?"}
            first = await client.post("/research", json=body)
            second = await client.post("/research", json=body)
    finally:
        api.settings.research_rate_limit_requests = old_limit
        api._request_times.clear()

    assert first.status_code == 202
    assert second.status_code == 429
    assert int(second.headers["retry-after"]) > 0


@pytest.mark.asyncio
async def test_workflow_marks_run_started_before_first_graph_node(monkeypatch: pytest.MonkeyPatch) -> None:
    statuses: list[str] = []
    snapshots: list[dict] = []

    async def fake_save_run(research_id: UUID, question: str, state: dict, status: str, **kwargs: object) -> None:
        statuses.append(status)
        snapshots.append(state)

    class FakeGraph:
        async def astream(self, initial: dict, **kwargs: object):
            assert statuses == ["running"]
            assert initial["audit_log"][0].action == "workflow_started"
            yield initial

    monkeypatch.setattr(api, "save_run", fake_save_run)
    monkeypatch.setattr(api, "research_graph", FakeGraph())
    monkeypatch.setattr(api, "paper_review_completion_issue", lambda state: None)

    await api._run_workflow(UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"), "What evidence supports this mechanism?")

    assert statuses == ["running", "running", "completed"]
    assert snapshots[0]["audit_log"][0].action == "workflow_started"


def test_rate_limit_state_prunes_expired_clients_but_keeps_active_ones() -> None:
    from collections import deque

    api._request_times.clear()
    api._last_rate_limit_prune = 0.0
    api._request_times["expired"] = deque([10.0, 20.0])
    api._request_times["empty"] = deque()
    api._request_times["active"] = deque([95.0])

    api._prune_rate_limit_state(now=100.0, window=60.0)

    assert set(api._request_times) == {"active"}
    # A second call inside the same window does nothing (amortized sweep).
    api._request_times["late"] = deque([1.0])
    api._prune_rate_limit_state(now=110.0, window=60.0)
    assert "late" in api._request_times
    api._request_times.clear()


@pytest.mark.asyncio
async def test_rate_limit_is_tracked_per_client_address(monkeypatch: pytest.MonkeyPatch) -> None:
    api._request_times.clear()
    old_limit = api.settings.research_rate_limit_requests
    api.settings.research_rate_limit_requests = 1
    monkeypatch.setattr(api, "create_research", AsyncMock(return_value=UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")))
    monkeypatch.setattr(api, "_run_workflow", AsyncMock())
    body = {"question": "What evidence supports this mechanism?"}
    try:
        async def post_from(host: str) -> int:
            transport = httpx.ASGITransport(app=api.app, client=(host, 5000))
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return (await client.post("/research", json=body)).status_code

        assert await post_from("203.0.113.1") == 202
        assert await post_from("203.0.113.2") == 202  # different user, own budget
        assert await post_from("203.0.113.1") == 429  # first user is now limited
    finally:
        api.settings.research_rate_limit_requests = old_limit
        api._request_times.clear()
