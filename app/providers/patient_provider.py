"""Patient provider — DB-backed storage for leads (simulation + production).

The original Precise Imaging build had a second `LivePatientProvider` that
pulled patient records from the RadFlow CallListData API. For the attorney
cold-call autocaller there is no external source of record; leads are
ingested from CSV into the local DB, so only the DB-backed provider remains.
"""
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal
from app.db.models import PatientRow
from app.models import Patient, Language, IntakeStatus

logger = logging.getLogger(__name__)


def _row_to_patient(row: PatientRow) -> Patient:
    try:
        lang = Language(row.language)
    except ValueError:
        lang = Language.ENGLISH
    try:
        intake = IntakeStatus(row.intake_status)
    except ValueError:
        intake = IntakeStatus.COMPLETE

    p = Patient.__new__(Patient)
    p.patient_id = row.patient_id
    p.name = row.name
    p.phone = row.phone
    p.language = lang
    p.order_id = row.order_id
    p.order_created = row.order_created
    p.intake_status = intake
    p.has_called_in_before = row.has_called_in_before
    p.has_abandoned_before = row.has_abandoned_before
    p.ai_called_before = row.ai_called_before
    p.attempt_count = row.attempt_count
    p.last_attempt_at = row.last_attempt_at
    p.last_outcome = row.last_outcome
    p.due_by = row.due_by
    p.priority_bucket = row.priority_bucket
    return p


def _compute_priority(has_abandoned_before: bool, ai_called_before: bool,
                       has_called_in_before: bool) -> int:
    if has_abandoned_before and not ai_called_before:
        return 1
    elif has_abandoned_before and ai_called_before:
        return 2
    elif not ai_called_before and has_called_in_before:
        return 3
    else:
        return 4


def _map_language(lang_str: str) -> Language:
    """Map RadFlow LANGUAGE string to Language enum."""
    mapping = {
        "english": Language.ENGLISH,
        "spanish": Language.SPANISH,
        "chinese": Language.CHINESE,
    }
    return mapping.get(lang_str.lower().strip(), Language.ENGLISH) if lang_str else Language.ENGLISH




# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------
class BasePatientProvider(ABC):
    """Interface for patient data access."""

    @abstractmethod
    async def get_all_patients(self) -> list[Patient]:
        ...

    @abstractmethod
    async def get_patient(self, patient_id: str) -> Optional[Patient]:
        ...

    @abstractmethod
    async def get_outbound_queue(self, max_attempts: int = 3, min_hours_between: int = 6) -> list[Patient]:
        ...

    @abstractmethod
    async def get_next_candidate(self, max_attempts: int = 3, min_hours_between: int = 6) -> Optional[Patient]:
        ...

    @abstractmethod
    async def update_patient_after_call(self, patient_id: str, outcome: str, increment_attempt: bool = True):
        ...

    @abstractmethod
    async def mark_patient_invalid_number(self, patient_id: str, reason: str):
        ...


# ---------------------------------------------------------------------------
# Simulation (DB-backed) provider
# ---------------------------------------------------------------------------
class SimulationPatientProvider(BasePatientProvider):
    """Manages patient records with PostgreSQL storage (simulation mode)."""

    async def get_all_patients(self) -> list[Patient]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PatientRow).order_by(PatientRow.priority_bucket, PatientRow.due_by)
            )
            return [_row_to_patient(r) for r in result.scalars().all()]

    async def get_patient(self, patient_id: str) -> Optional[Patient]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PatientRow).where(PatientRow.patient_id == patient_id)
            )
            row = result.scalar_one_or_none()
            return _row_to_patient(row) if row else None

    async def get_outbound_queue(self, max_attempts: int = 3, min_hours_between: int = 6) -> list[Patient]:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=min_hours_between)

        async with AsyncSessionLocal() as session:
            stmt = (
                select(PatientRow)
                .where(PatientRow.attempt_count < max_attempts)
                .where(
                    (PatientRow.last_outcome == None) |  # noqa: E711
                    (PatientRow.last_outcome != "invalid_number")
                )
                .where(
                    (PatientRow.last_attempt_at == None) |  # noqa: E711
                    (PatientRow.last_attempt_at <= cutoff)
                )
                .order_by(
                    PatientRow.priority_bucket,
                    PatientRow.due_by.asc().nulls_last(),
                    PatientRow.order_created.asc().nulls_last(),
                    PatientRow.attempt_count,
                )
            )
            result = await session.execute(stmt)
            return [_row_to_patient(r) for r in result.scalars().all()]

    async def get_next_candidate(self, max_attempts: int = 3, min_hours_between: int = 6) -> Optional[Patient]:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=min_hours_between)

        async with AsyncSessionLocal() as session:
            stmt = (
                select(PatientRow)
                .where(PatientRow.attempt_count < max_attempts)
                .where(
                    (PatientRow.last_outcome == None) |  # noqa: E711
                    (PatientRow.last_outcome != "invalid_number")
                )
                .where(
                    (PatientRow.last_attempt_at == None) |  # noqa: E711
                    (PatientRow.last_attempt_at <= cutoff)
                )
                .order_by(
                    PatientRow.priority_bucket,
                    PatientRow.due_by.asc().nulls_last(),
                    PatientRow.order_created.asc().nulls_last(),
                    PatientRow.attempt_count,
                )
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return _row_to_patient(row) if row else None

    async def update_patient_after_call(
        self,
        patient_id: str,
        outcome: str,
        increment_attempt: bool = True,
    ):
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PatientRow).where(PatientRow.patient_id == patient_id)
            )
            row = result.scalar_one_or_none()
            if row:
                if increment_attempt:
                    row.attempt_count += 1
                row.last_attempt_at = datetime.now(timezone.utc)
                row.last_outcome = outcome
                row.ai_called_before = True
                row.priority_bucket = _compute_priority(
                    row.has_abandoned_before, row.ai_called_before, row.has_called_in_before
                )
                await session.commit()

    async def mark_patient_invalid_number(self, patient_id: str, reason: str):
        """Flag patient as invalid number to prevent retries."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PatientRow).where(PatientRow.patient_id == patient_id)
            )
            row = result.scalar_one_or_none()
            if row:
                row.last_outcome = "invalid_number"
                row.ai_called_before = True
                row.last_attempt_at = datetime.now(timezone.utc)
                await session.commit()
                logger.info("Patient %s flagged invalid_number: %s", patient_id, reason)

    # -- Simulation-only methods --

    async def add_patient(self, patient: Patient):
        async with AsyncSessionLocal() as session:
            row = PatientRow(
                patient_id=patient.patient_id,
                name=patient.name,
                phone=patient.phone,
                language=patient.language.value,
                order_id=patient.order_id,
                order_created=patient.order_created,
                intake_status=patient.intake_status.value,
                has_called_in_before=patient.has_called_in_before,
                has_abandoned_before=patient.has_abandoned_before,
                ai_called_before=patient.ai_called_before,
                attempt_count=patient.attempt_count,
                last_attempt_at=patient.last_attempt_at,
                last_outcome=patient.last_outcome,
                due_by=patient.due_by,
                priority_bucket=patient.priority_bucket,
            )
            session.add(row)
            await session.commit()

    async def remove_patient(self, patient_id: str):
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(PatientRow).where(PatientRow.patient_id == patient_id)
            )
            await session.commit()

    async def reset_with_patients(self, patient_dicts: list[dict]):
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as session:
            await session.execute(delete(PatientRow))
            for i, pd in enumerate(patient_dicts, start=1):
                lang_str = pd.get("language", "en")
                try:
                    lang = Language(lang_str)
                except ValueError:
                    lang = Language.ENGLISH

                has_abandoned = pd.get("has_abandoned_before", False)
                ai_called = pd.get("ai_called_before", False)
                has_called_in = pd.get("has_called_in_before", False)

                row = PatientRow(
                    patient_id=f"SIM{i:03d}",
                    name=pd["name"],
                    phone=pd["phone"],
                    language=lang.value,
                    order_id=f"ORD-SIM{i:03d}",
                    order_created=now - timedelta(days=1),
                    has_abandoned_before=has_abandoned,
                    has_called_in_before=has_called_in,
                    ai_called_before=ai_called,
                    attempt_count=pd.get("attempt_count", 0),
                    due_by=now + timedelta(days=2),
                    priority_bucket=_compute_priority(has_abandoned, ai_called, has_called_in),
                )
                session.add(row)
            await session.commit()

    async def reset_to_sample_data(self):
        """Reset to initial sample data by re-running seed."""
        from app.db.seed import seed_sample_patients
        async with AsyncSessionLocal() as session:
            await session.execute(delete(PatientRow))
            await session.commit()
        async with AsyncSessionLocal() as session:
            await seed_sample_patients(session)
            await session.commit()

# ---------------------------------------------------------------------------
# Singleton management — only the DB-backed provider exists.
# ---------------------------------------------------------------------------
_sim_provider: Optional[SimulationPatientProvider] = None


def _get_sim_provider() -> SimulationPatientProvider:
    global _sim_provider
    if _sim_provider is None:
        _sim_provider = SimulationPatientProvider()
    return _sim_provider


def get_patient_provider() -> BasePatientProvider:
    """Active patient provider — always the DB-backed one."""
    return _get_sim_provider()


def get_simulation_patient_provider() -> SimulationPatientProvider:
    """Kept for compatibility with endpoints that explicitly want the sim provider."""
    return _get_sim_provider()


def set_patient_source(source: str):
    """No-op — single patient source in the autocaller build."""
    return None


# Backwards-compatible alias
PatientProvider = SimulationPatientProvider
