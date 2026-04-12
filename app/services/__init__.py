"""Services for call orchestration."""
import asyncio
import logging
from typing import Coroutine

from .realtime_voice import RealtimeVoiceService
from .call_orchestrator import CallOrchestrator


def safe_create_task(
    coro: Coroutine,
    logger: logging.Logger,
    context_msg: str = "background task",
) -> asyncio.Task:
    """Wrap asyncio.create_task with a done-callback that logs exceptions."""
    task = asyncio.create_task(coro)

    def _done_cb(t: asyncio.Task):
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            logger.error("Unhandled error in %s: %s", context_msg, exc, exc_info=exc)

    task.add_done_callback(_done_cb)
    return task


__all__ = [
    "RealtimeVoiceService",
    "CallOrchestrator",
    "safe_create_task",
]
