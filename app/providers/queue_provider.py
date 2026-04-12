"""Queue provider — stub that always allows outbound.

The original Precise Imaging system gated outbound calls on FreePBX AMI
state (agents available, holdtime, stable polls). In the attorney cold-call
autocaller there is no inbound queue to protect, so this provider is a
trivial always-allow stub. The interface is preserved so the dispatcher
and other call sites keep working until they are simplified in Phase 6.
"""
import logging
from datetime import datetime
from typing import Optional

from app.models import GlobalQueueState

logger = logging.getLogger(__name__)


class MockQueueProvider:
    """Always-allow stub — no real queue, outbound permitted at all times."""

    def __init__(self):
        self._state = GlobalQueueState(
            global_agents_available=1,
            outbound_allowed=True,
            stable_polls_count=3,
            ami_connected=True,
            queues=[],
        )

    def get_state(self) -> GlobalQueueState:
        return self._state

    async def poll(self) -> GlobalQueueState:
        self._state.last_poll_time = datetime.now()
        self._state.outbound_allowed = True
        return self._state

    # -- No-op simulation hooks kept so legacy API endpoints don't crash --

    def set_queue_state(self, *args, **kwargs):
        return None

    def simulate_busy_queue(self):
        return None

    def simulate_quiet_queue(self):
        return None

    def simulate_ami_failure(self):
        return None

    def simulate_ami_recovery(self):
        return None

    def reset_with_config(self, *args, **kwargs):
        return None

    def add_queue(self, *args, **kwargs):
        return None


# ---------------------------------------------------------------------------
# Singleton management — kept to preserve the existing public interface.
# ---------------------------------------------------------------------------
_mock_provider: Optional[MockQueueProvider] = None


def _get_mock_provider() -> MockQueueProvider:
    global _mock_provider
    if _mock_provider is None:
        _mock_provider = MockQueueProvider()
    return _mock_provider


def get_queue_provider() -> MockQueueProvider:
    """Active queue provider — always the stub."""
    return _get_mock_provider()


def get_mock_queue_provider() -> MockQueueProvider:
    """Kept for compatibility with legacy simulation endpoints."""
    return _get_mock_provider()


def set_queue_source(source: str):
    """No-op — single queue source in the autocaller build."""
    return None
