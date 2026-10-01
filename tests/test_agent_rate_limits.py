from typing import Any

import pytest

from auditable_research import agents
from auditable_research.agents import GroqRateLimited, PlanOutput


@pytest.mark.asyncio
async def test_long_retry_after_fails_fast_without_sleep_or_repeated_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    class RateLimitResponse:
        headers = {"retry-after": "180"}

    class RateLimitError(Exception):
        status_code = 429
        response = RateLimitResponse()

    class LimitedModel:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, messages: list[tuple[str, str]]) -> Any:
            self.calls += 1
            raise RateLimitError("rate limit")

    model = LimitedModel()

    def model_factory(schema: type[Any], model_name: str | None = None) -> LimitedModel:
        return model

    monkeypatch.setattr(agents, "_structured_model", model_factory)
    monkeypatch.setattr(agents.settings, "groq_max_retry_wait_seconds", 5)
    monkeypatch.setattr(agents.settings, "groq_max_retries", 3)

    with pytest.raises(GroqRateLimited) as raised:
        await agents.invoke_structured(PlanOutput, [("user", "test")])

    assert raised.value.retry_after_seconds == 180
    assert model.calls == 1
