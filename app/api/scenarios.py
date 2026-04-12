"""Scenarios API endpoints - full CRUD for simulation scenarios."""
import uuid
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete

from app.db import AsyncSessionLocal
from app.db.models import SimulationScenarioRow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


class QueueConfigItem(BaseModel):
    Queue: str
    Calls: int = 0
    Holdtime: int = 0
    AvailableAgents: int = 0


class PatientConfigItem(BaseModel):
    name: str
    phone: str
    language: str = "en"
    has_abandoned_before: bool = False
    has_called_in_before: bool = False
    ai_called_before: bool = False
    attempt_count: int = 0


class ScenarioResponse(BaseModel):
    id: str
    label: str
    description: str
    is_builtin: bool
    ami_connected: bool
    queues: List[dict]
    patients: List[dict]
    created_at: str
    updated_at: str


class ScenarioCreateRequest(BaseModel):
    label: str
    description: str = ""
    ami_connected: bool = True
    queues: List[QueueConfigItem] = []
    patients: List[PatientConfigItem] = []


class ScenarioUpdateRequest(BaseModel):
    label: Optional[str] = None
    description: Optional[str] = None
    ami_connected: Optional[bool] = None
    queues: Optional[List[QueueConfigItem]] = None
    patients: Optional[List[PatientConfigItem]] = None


def _row_to_response(row: SimulationScenarioRow) -> ScenarioResponse:
    return ScenarioResponse(
        id=row.id,
        label=row.label,
        description=row.description,
        is_builtin=row.is_builtin,
        ami_connected=row.ami_connected,
        queues=row.queues or [],
        patients=row.patients or [],
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
    )


@router.get("", response_model=List[ScenarioResponse])
async def list_scenarios():
    """List all simulation scenarios."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SimulationScenarioRow).order_by(SimulationScenarioRow.label)
        )
        rows = result.scalars().all()
        return [_row_to_response(row) for row in rows]


@router.get("/{scenario_id}", response_model=ScenarioResponse)
async def get_scenario(scenario_id: str):
    """Get a single scenario by ID."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SimulationScenarioRow).where(SimulationScenarioRow.id == scenario_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            print(f"[GET_SCENARIO] Scenario not found: {scenario_id}")
            raise HTTPException(status_code=404, detail="Scenario not found")
        print(f"[GET_SCENARIO] Loaded scenario '{row.label}' with {len(row.patients or [])} patients")
        return _row_to_response(row)


@router.post("", response_model=ScenarioResponse, status_code=201)
async def create_scenario(request: ScenarioCreateRequest):
    """Create a new custom scenario."""
    async with AsyncSessionLocal() as session:
        scenario_id = str(uuid.uuid4())[:8]
        row = SimulationScenarioRow(
            id=scenario_id,
            label=request.label,
            description=request.description,
            is_builtin=False,
            ami_connected=request.ami_connected,
            queues=[q.model_dump() for q in request.queues],
            patients=[p.model_dump() for p in request.patients],
            dispatcher={},
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return _row_to_response(row)


@router.put("/{scenario_id}", response_model=ScenarioResponse)
async def update_scenario(scenario_id: str, request: ScenarioUpdateRequest):
    """Update an existing scenario."""
    from app.providers import get_settings_provider, get_simulation_patient_provider, get_mock_queue_provider

    print(f"[UPDATE_SCENARIO] Updating scenario: {scenario_id}")
    if request.patients is not None:
        print(f"[UPDATE_SCENARIO] New patients list has {len(request.patients)} patients")
        for p in request.patients:
            print(f"[UPDATE_SCENARIO] - Patient: {p.name}, {p.phone}")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SimulationScenarioRow).where(SimulationScenarioRow.id == scenario_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            print(f"[UPDATE_SCENARIO] Scenario not found: {scenario_id}")
            raise HTTPException(status_code=404, detail="Scenario not found")

        old_patient_count = len(row.patients or [])
        print(f"[UPDATE_SCENARIO] Current scenario '{row.label}' has {old_patient_count} patients")

        if request.label is not None:
            row.label = request.label
        if request.description is not None:
            row.description = request.description
        if request.ami_connected is not None:
            row.ami_connected = request.ami_connected
        if request.queues is not None:
            row.queues = [q.model_dump() for q in request.queues]
        if request.patients is not None:
            row.patients = [p.model_dump() for p in request.patients]

        await session.commit()
        await session.refresh(row)

        new_patient_count = len(row.patients or [])
        print(f"[UPDATE_SCENARIO] Saved scenario '{row.label}': {old_patient_count} -> {new_patient_count} patients")

        # If this is the active scenario, reload patients into PatientRow table
        settings_provider = get_settings_provider()
        settings = await settings_provider.get_settings()
        if settings.active_scenario_id == scenario_id:
            print(f"[UPDATE_SCENARIO] This is the active scenario, reloading patients into PatientRow table")
            patient_provider = get_simulation_patient_provider()
            await patient_provider.reset_with_patients(row.patients or [])
            print(f"[UPDATE_SCENARIO] Reloaded {len(row.patients or [])} patients into PatientRow table")

            # Also reload queues if they were updated
            if request.queues is not None or request.ami_connected is not None:
                queue_provider = get_mock_queue_provider()
                queue_provider.reset_with_config(
                    queues_config=row.queues or [],
                    ami_connected=row.ami_connected,
                )
                print(f"[UPDATE_SCENARIO] Reloaded queue configuration")

        return _row_to_response(row)


@router.delete("/{scenario_id}")
async def delete_scenario(scenario_id: str):
    """Delete a scenario. Cannot delete builtin scenarios."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SimulationScenarioRow).where(SimulationScenarioRow.id == scenario_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Scenario not found")

        await session.execute(
            delete(SimulationScenarioRow).where(SimulationScenarioRow.id == scenario_id)
        )
        await session.commit()
        return {"status": "ok", "deleted_id": scenario_id}


@router.delete("")
async def delete_all_custom_scenarios():
    """Delete all custom (non-builtin) simulation scenarios."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(SimulationScenarioRow).where(
                SimulationScenarioRow.is_builtin == False  # noqa: E712
            )
        )
        await session.commit()
        return {"status": "ok", "deleted": result.rowcount}
