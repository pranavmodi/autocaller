"""Seed default data into the database on startup."""
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import SystemSettingsRow, PatientRow, SimulationScenarioRow

logger = logging.getLogger(__name__)


async def seed_default_settings(session: AsyncSession):
    """Insert the singleton settings row if it doesn't exist."""
    result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
    if result.scalar_one_or_none() is not None:
        return
    row = SystemSettingsRow(
        id=1,
        system_enabled=True,
        business_hours={
            "start_time": "08:00",
            "end_time": "17:00",
            "enabled": False,
            "timezone": "America/New_York",
            "days_of_week": [0, 1, 2, 3, 4],  # Mon-Fri
            "holidays": [],
        },
        queue_thresholds={
            "calls_waiting_threshold": 1,
            "holdtime_threshold_seconds": 30,
            "stable_polls_required": 3,
        },
        dispatcher_settings={
            "poll_interval": 10,
            "dispatch_timeout": 30,
            "max_attempts": 3,
            "min_hours_between": 6,
        },
        allow_live_calls=False,
        allowed_phones=[],
        queue_source="simulation",
        patient_source="simulation",
    )
    session.add(row)
    logger.info("Seeded default system settings")


async def seed_sample_patients(session: AsyncSession):
    """Insert sample patients if the table is empty."""
    result = await session.execute(select(PatientRow.patient_id).limit(1))
    if result.scalar_one_or_none() is not None:
        return

    now = datetime.now(timezone.utc)
    samples = [
        PatientRow(
            patient_id="PRE001", name="John Smith", phone="555-0101",
            language="en", order_id="ORD001",
            order_created=now - timedelta(days=1),
            has_abandoned_before=True, ai_called_before=False,
            due_by=now + timedelta(days=1), priority_bucket=1,
        ),
        PatientRow(
            patient_id="PRE002", name="Maria Garcia", phone="555-0102",
            language="es", order_id="ORD002",
            order_created=now - timedelta(days=2),
            has_abandoned_before=True, ai_called_before=False,
            due_by=now, priority_bucket=1,
        ),
        PatientRow(
            patient_id="PRE003", name="Robert Johnson", phone="555-0103",
            language="en", order_id="ORD003",
            order_created=now - timedelta(days=1),
            has_abandoned_before=True, ai_called_before=True,
            attempt_count=1, last_attempt_at=now - timedelta(hours=8),
            last_outcome="no_answer",
            due_by=now + timedelta(days=1), priority_bucket=2,
        ),
        PatientRow(
            patient_id="PRE004", name="Emily Davis", phone="555-0104",
            language="en", order_id="ORD004",
            order_created=now - timedelta(hours=12),
            has_called_in_before=True, ai_called_before=False,
            due_by=now + timedelta(days=2), priority_bucket=3,
        ),
        PatientRow(
            patient_id="PRE005", name="Michael Wilson", phone="555-0105",
            language="en", order_id="ORD005",
            order_created=now - timedelta(hours=6),
            ai_called_before=False,
            due_by=now + timedelta(days=2), priority_bucket=4,
        ),
        PatientRow(
            patient_id="PRE006", name="Sarah Brown", phone="555-0106",
            language="en", order_id="ORD006",
            order_created=now - timedelta(hours=3),
            intake_status="incomplete", ai_called_before=False,
            due_by=now + timedelta(days=2), priority_bucket=4,
        ),
        PatientRow(
            patient_id="PRE007", name="Wei Zhang", phone="555-0107",
            language="zh", order_id="ORD007",
            order_created=now - timedelta(hours=18),
            has_called_in_before=True, ai_called_before=False,
            due_by=now + timedelta(days=1), priority_bucket=3,
        ),
    ]
    session.add_all(samples)
    logger.info("Seeded %d sample patients", len(samples))


async def seed_builtin_scenarios(session: AsyncSession):
    """Seed built-in simulation scenarios if they don't already exist.

    Only creates scenarios that are missing - preserves any user modifications.
    """
    # Get existing scenario IDs
    result = await session.execute(select(SimulationScenarioRow.id))
    existing_ids = {row[0] for row in result.fetchall()}

    scenarios = [
        SimulationScenarioRow(
            id="single_patient_ready",
            label="Single Patient Ready",
            description="One patient waiting, one agent available. Simplest scenario to trigger a single outbound call immediately.",
            is_builtin=True,
            ami_connected=True,
            queues=[
                {"Queue": "9006", "Calls": 0, "Holdtime": 0, "AvailableAgents": 1},
            ],
            patients=[
                {"name": "Pranav Modi", "phone": "+918287149638", "language": "en",
                 "has_abandoned_before": True, "has_called_in_before": False,
                 "ai_called_before": False, "attempt_count": 0},
            ],
            dispatcher={},
        ),
        SimulationScenarioRow(
            id="default_full_queue",
            label="Default (Full Queue)",
            description="3 queues with agents available, 7 patients across all priority buckets. Standard dispatcher settings.",
            is_builtin=True,
            ami_connected=True,
            queues=[
                {"Queue": "9006", "Calls": 0, "Holdtime": 0, "AvailableAgents": 2},
                {"Queue": "9009", "Calls": 0, "Holdtime": 0, "AvailableAgents": 1},
                {"Queue": "9012", "Calls": 0, "Holdtime": 0, "AvailableAgents": 1},
            ],
            patients=[
                {"name": "John Smith", "phone": "555-0101", "language": "en",
                 "has_abandoned_before": True, "has_called_in_before": False,
                 "ai_called_before": False, "attempt_count": 0},
                {"name": "Maria Garcia", "phone": "555-0102", "language": "es",
                 "has_abandoned_before": True, "has_called_in_before": False,
                 "ai_called_before": False, "attempt_count": 0},
                {"name": "Robert Johnson", "phone": "555-0103", "language": "en",
                 "has_abandoned_before": True, "has_called_in_before": False,
                 "ai_called_before": True, "attempt_count": 1},
                {"name": "Emily Davis", "phone": "555-0104", "language": "en",
                 "has_abandoned_before": False, "has_called_in_before": True,
                 "ai_called_before": False, "attempt_count": 0},
                {"name": "Michael Wilson", "phone": "555-0105", "language": "en",
                 "has_abandoned_before": False, "has_called_in_before": False,
                 "ai_called_before": False, "attempt_count": 0},
                {"name": "Sarah Brown", "phone": "555-0106", "language": "en",
                 "has_abandoned_before": False, "has_called_in_before": False,
                 "ai_called_before": False, "attempt_count": 0},
                {"name": "Wei Zhang", "phone": "555-0107", "language": "zh",
                 "has_abandoned_before": False, "has_called_in_before": True,
                 "ai_called_before": False, "attempt_count": 0},
            ],
            dispatcher={},
        ),
        SimulationScenarioRow(
            id="busy_queues",
            label="Busy Queues (Blocked)",
            description="All queues are overloaded with calls waiting and no agents free. Outbound should be blocked by gating conditions.",
            is_builtin=True,
            ami_connected=True,
            queues=[
                {"Queue": "9006", "Calls": 5, "Holdtime": 120, "AvailableAgents": 0},
                {"Queue": "9009", "Calls": 3, "Holdtime": 90, "AvailableAgents": 0},
                {"Queue": "9012", "Calls": 4, "Holdtime": 60, "AvailableAgents": 0},
            ],
            patients=[
                {"name": "John Smith", "phone": "555-0101", "language": "en",
                 "has_abandoned_before": True, "has_called_in_before": False,
                 "ai_called_before": False, "attempt_count": 0},
                {"name": "Maria Garcia", "phone": "555-0102", "language": "es",
                 "has_abandoned_before": True, "has_called_in_before": False,
                 "ai_called_before": False, "attempt_count": 0},
            ],
            dispatcher={},
        ),
        SimulationScenarioRow(
            id="ami_down",
            label="AMI Disconnected",
            description="AMI connection is down. Dispatcher will block all outbound calls regardless of queue or patient state.",
            is_builtin=True,
            ami_connected=False,
            queues=[
                {"Queue": "9006", "Calls": 0, "Holdtime": 0, "AvailableAgents": 2},
            ],
            patients=[
                {"name": "John Smith", "phone": "555-0101", "language": "en",
                 "has_abandoned_before": True, "has_called_in_before": False,
                 "ai_called_before": False, "attempt_count": 0},
            ],
            dispatcher={},
        ),
        SimulationScenarioRow(
            id="multilingual",
            label="Multilingual Patients",
            description="Three patients in different languages (EN, ES, ZH), one agent available. Tests language routing.",
            is_builtin=True,
            ami_connected=True,
            queues=[
                {"Queue": "9006", "Calls": 0, "Holdtime": 0, "AvailableAgents": 1},
                {"Queue": "9009", "Calls": 0, "Holdtime": 0, "AvailableAgents": 1},
            ],
            patients=[
                {"name": "John Smith", "phone": "555-0101", "language": "en",
                 "has_abandoned_before": True, "has_called_in_before": False,
                 "ai_called_before": False, "attempt_count": 0},
                {"name": "Maria Garcia", "phone": "555-0102", "language": "es",
                 "has_abandoned_before": True, "has_called_in_before": False,
                 "ai_called_before": False, "attempt_count": 0},
                {"name": "Wei Zhang", "phone": "555-0107", "language": "zh",
                 "has_abandoned_before": False, "has_called_in_before": True,
                 "ai_called_before": False, "attempt_count": 0},
            ],
            dispatcher={},
        ),
        SimulationScenarioRow(
            id="retry_scenario",
            label="Retry Exhaustion",
            description="Two patients near their max attempt limit. One has 2/3 attempts used, the other has 3/3 (exhausted). Only the first should be eligible.",
            is_builtin=True,
            ami_connected=True,
            queues=[
                {"Queue": "9006", "Calls": 0, "Holdtime": 0, "AvailableAgents": 1},
            ],
            patients=[
                {"name": "Robert Johnson", "phone": "555-0103", "language": "en",
                 "has_abandoned_before": True, "has_called_in_before": False,
                 "ai_called_before": True, "attempt_count": 2},
                {"name": "Emily Davis", "phone": "555-0104", "language": "en",
                 "has_abandoned_before": False, "has_called_in_before": True,
                 "ai_called_before": True, "attempt_count": 3},
            ],
            dispatcher={},
        ),
        SimulationScenarioRow(
            id="empty_queue",
            label="No Patients",
            description="Agents available but no patients in the outbound queue. Dispatcher should tick but find no candidate.",
            is_builtin=True,
            ami_connected=True,
            queues=[
                {"Queue": "9006", "Calls": 0, "Holdtime": 0, "AvailableAgents": 2},
            ],
            patients=[],
            dispatcher={},
        ),
    ]
    # Only add scenarios that don't already exist
    new_scenarios = [s for s in scenarios if s.id not in existing_ids]
    if new_scenarios:
        session.add_all(new_scenarios)
        print(f"[SEED] Seeded {len(new_scenarios)} new simulation scenarios")
        for s in new_scenarios:
            print(f"[SEED] - Created scenario '{s.label}' with {len(s.patients or [])} patients")
    else:
        print("[SEED] All simulation scenarios already exist, skipping seed")

    # Log existing scenarios
    for s in scenarios:
        if s.id in existing_ids:
            print(f"[SEED] - Scenario '{s.id}' already exists, preserving user data")

    # Set active_scenario_id to single_patient_ready if NULL
    result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
    settings_row = result.scalar_one_or_none()
    if settings_row and settings_row.active_scenario_id is None:
        settings_row.active_scenario_id = "single_patient_ready"
        logger.info("Set default active_scenario_id to 'single_patient_ready'")
