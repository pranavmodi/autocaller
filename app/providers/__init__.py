"""Providers for external systems — DB-backed."""
from .queue_provider import (
    MockQueueProvider,
    get_queue_provider,
    get_mock_queue_provider,
    set_queue_source,
)
from .patient_provider import (
    PatientProvider,
    get_patient_provider,
    get_simulation_patient_provider,
    set_patient_source,
)
from .call_log_provider import CallLogProvider, get_call_log_provider
from .settings_provider import SettingsProvider, get_settings_provider

__all__ = [
    "MockQueueProvider",
    "PatientProvider",
    "CallLogProvider",
    "SettingsProvider",
    "get_queue_provider",
    "get_mock_queue_provider",
    "set_queue_source",
    "get_patient_provider",
    "get_simulation_patient_provider",
    "set_patient_source",
    "get_call_log_provider",
    "get_settings_provider",
]
