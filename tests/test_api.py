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
