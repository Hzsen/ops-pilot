from __future__ import annotations

from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, status

from .domain import (
    ApprovalDecision,
    ApprovalRecord,
    Incident,
    IncidentCreate,
    TriageReport,
)
from .repository import IncidentNotFoundError, InMemoryIncidentRepository
from .triage import TriageEngine


def create_app() -> FastAPI:
    application = FastAPI(title="OpsPilot", version="0.1.0")
    repository = InMemoryIncidentRepository()
    engine = TriageEngine()

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "policy": "human-approval-required"}

    @application.post(
        "/api/incidents", response_model=Incident, status_code=status.HTTP_201_CREATED
    )
    def create_incident(payload: IncidentCreate) -> Incident:
        incident = Incident(incident_id=str(uuid4()), **payload.model_dump())
        return repository.create(incident)

    @application.get("/api/incidents/{incident_id}", response_model=Incident)
    def get_incident(incident_id: str) -> Incident:
        try:
            return repository.get(incident_id)
        except IncidentNotFoundError as error:
            raise HTTPException(status_code=404, detail="incident not found") from error

    @application.post(
        "/api/incidents/{incident_id}/triage", response_model=TriageReport
    )
    def triage_incident(incident_id: str) -> TriageReport:
        try:
            incident = repository.get(incident_id)
        except IncidentNotFoundError as error:
            raise HTTPException(status_code=404, detail="incident not found") from error
        return repository.save_report(engine.triage(incident))

    @application.post(
        "/api/incidents/{incident_id}/approvals", response_model=ApprovalRecord
    )
    def record_approval(
        incident_id: str, payload: ApprovalDecision
    ) -> ApprovalRecord:
        record = ApprovalRecord(incident_id=incident_id, **payload.model_dump())
        try:
            return repository.record_approval(record)
        except IncidentNotFoundError as error:
            raise HTTPException(status_code=404, detail="triage report not found") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return application


app = create_app()


def run() -> None:
    uvicorn.run("opspilot.api:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    run()

