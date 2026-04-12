"""Shared fixtures for unit tests."""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from app.models import CallLog, CallOutcome, Patient, Language, TranscriptEntry


@pytest.fixture
def sample_call():
    """A basic in-progress call."""
    return CallLog(
        call_id="test-call-001",
        patient_id="PAT-001",
        patient_name="Jane Doe",
        phone="+15551234567",
        order_id="ORD-001",
        priority_bucket=1,
    )


@pytest.fixture
def sample_patient():
    """A basic patient fixture."""
    return Patient(
        patient_id="PAT-001",
        name="Jane Doe",
        phone="+15551234567",
        language=Language.ENGLISH,
        order_id="ORD-001",
    )


@pytest.fixture
def sample_patient_spanish():
    return Patient(
        patient_id="PAT-002",
        name="Maria Garcia",
        phone="+15559876543",
        language=Language.SPANISH,
        order_id="ORD-002",
    )


@pytest.fixture
def mock_call_log_provider():
    """Mock call log provider for tests."""
    provider = AsyncMock()
    provider.get_call = AsyncMock(return_value=None)
    provider.update_call = AsyncMock()
    provider.add_transcript = AsyncMock()
    provider.end_call = AsyncMock()
    return provider


@pytest.fixture
def mock_patient_provider():
    """Mock patient provider for tests."""
    provider = AsyncMock()
    provider.mark_patient_invalid_number = AsyncMock()
    return provider


@pytest.fixture
def mock_queue_state():
    """Mock queue state with configurable queues."""
    queue = MagicMock()
    queue.Queue = "9006"
    queue.AvailableAgents = 2

    state = MagicMock()
    state.queues = [queue]
    state.outbound_allowed = True
    return state
