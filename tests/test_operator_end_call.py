import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.api import dashboard
from app.models.call_log import CallOutcome


def test_end_operator_call_repairs_terminal_call_still_marked_in_progress(monkeypatch):
    call = SimpleNamespace(
        call_id="call-1",
        ended_at=datetime.now(timezone.utc),
        termination_state="carrier_confirmed_ended",
        outcome=CallOutcome.IN_PROGRESS,
    )
    provider = MagicMock()
    provider.get_call = AsyncMock(return_value=call)
    provider.end_call = AsyncMock()
    provider.clear_active_call = MagicMock()
    monkeypatch.setattr(dashboard, "get_call_log_provider", lambda: provider)

    result = asyncio.run(dashboard.end_operator_call("call-1"))

    assert result == {"status": "ended", "call_id": "call-1", "already_terminal": True}
    provider.end_call.assert_awaited_once_with(
        "call-1", CallOutcome.COMPLETED, ended_by="manual",
    )
    provider.clear_active_call.assert_called_once()


def test_end_operator_call_closes_stale_row_without_carrier_handle(monkeypatch):
    call = SimpleNamespace(
        call_id="call-2", ended_at=None, termination_state="live",
        outcome=CallOutcome.IN_PROGRESS, carrier_call_sid=None,
    )
    provider = MagicMock()
    provider.get_call = AsyncMock(return_value=call)
    provider.end_call = AsyncMock()
    provider.mark_carrier_terminal = AsyncMock()
    provider.clear_active_call = MagicMock()
    orchestrator = SimpleNamespace(_current_call=None, _ending_call=False)
    monkeypatch.setattr(dashboard, "get_call_log_provider", lambda: provider)
    monkeypatch.setattr(dashboard, "get_orchestrator", lambda: orchestrator)

    result = asyncio.run(dashboard.end_operator_call("call-2"))

    assert result["carrier_handle_missing"] is True
    provider.mark_carrier_terminal.assert_awaited_once_with(
        "call-2",
        state="carrier_confirmed_ended",
        error="manual_end_no_carrier_handle_after_restart",
    )
