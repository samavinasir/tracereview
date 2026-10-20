"""Long-running PostgreSQL queue consumer. Run with ``python -m tracereview_web.worker``."""

import asyncio
import logging
import os
import socket
import uuid

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tracereview_web.settings")

from auditable_research.provider_credentials import MODEL_PROVIDER_PREFERENCE_KEY, decrypt_provider_keys
from auditable_research.storage import (
    claim_research_job,
    engine,
    finish_research_job,
    get_status,
    initialize_storage,
    release_research_job,
    renew_research_job_lease,
)
from auditable_research.workflow_runtime import run_workflow

logger = logging.getLogger("tracereview.worker")
LEASE_SECONDS = 180
HEARTBEAT_SECONDS = 45
POLL_SECONDS = 2
MAX_ATTEMPTS = 3


async def _provider_keys(user_id: int | None) -> dict[str, str] | None:
    if user_id is None:
        return None
    import django

    django.setup()
    from tracereview_web.research.models import UserProviderCredentials

    row = await UserProviderCredentials.objects.filter(user_id=user_id).afirst()
    keys = decrypt_provider_keys(row.encrypted_keys if row else None)
    if row:
        keys[MODEL_PROVIDER_PREFERENCE_KEY] = row.preferred_model_provider
    return keys


async def _process(job: dict, worker_id: str) -> None:
    research_id = job["research_id"]
    try:
        keys = await _provider_keys(job["user_id"])
        workflow = asyncio.create_task(run_workflow(
            research_id,
            job["question"],
            job["research_options"],
            provider_keys=keys,
        ))
        while not workflow.done():
            done, _ = await asyncio.wait({workflow}, timeout=HEARTBEAT_SECONDS)
            if done:
                break
            try:
                owned = await renew_research_job_lease(research_id, worker_id, LEASE_SECONDS)
            except Exception as exc:
                logger.warning("Queue heartbeat failed run_id=%s error_type=%s", research_id, type(exc).__name__)
                continue
            if not owned:
                workflow.cancel()
                await asyncio.gather(workflow, return_exceptions=True)
                logger.warning("Worker lost job lease run_id=%s", research_id)
                return
        await workflow
        status_data = await get_status(research_id)
        status = status_data.get("status", "failed") if status_data else "failed"
        await finish_research_job(research_id, worker_id, status, max_attempts=MAX_ATTEMPTS)
    except Exception as exc:
        logger.error("Research job processing failed run_id=%s error_type=%s", research_id, type(exc).__name__)
        try:
            await release_research_job(research_id, worker_id, f"Worker error: {type(exc).__name__}")
        except Exception as release_exc:
            logger.error("Could not release job run_id=%s error_type=%s", research_id, type(release_exc).__name__)


async def run_worker() -> None:
    worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:12]}"
    await initialize_storage()
    logger.info("Research worker started worker_id=%s", worker_id)
    try:
        while True:
            try:
                job = await claim_research_job(worker_id, LEASE_SECONDS, MAX_ATTEMPTS)
                if job is None:
                    await asyncio.sleep(POLL_SECONDS)
                    continue
                logger.info("Claimed research run_id=%s attempt=%d", job["research_id"], job["attempts"])
                await _process(job, worker_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Queue polling failed error_type=%s", type(exc).__name__)
                await asyncio.sleep(POLL_SECONDS)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    asyncio.run(run_worker())
