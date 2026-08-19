from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class IncidentStatus(StrEnum):
    OPEN = "open"
    TRIAGED = "triaged"


class IncidentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    service: str = Field(min_length=2, max_length=100)
    logs: list[str] = Field(default_factory=list, max_length=500)
    metrics: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_observable_input(self) -> IncidentCreate:
        if not self.logs and not self.metrics:
            raise ValueError("at least one log line or metric is required")
        return self


class Incident(IncidentCreate):
    incident_id: str
    status: IncidentStatus = IncidentStatus.OPEN
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Evidence(BaseModel):
    evidence_id: str
    source_type: Literal[
        "log",
        "metric",
        "runbook",
        "data_profile",
        "calendar",
        "corporate_action",
    ]
    source_ref: str
    excerpt: str = Field(min_length=1, max_length=500)


class Hypothesis(BaseModel):
    statement: str
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)


class ProposedAction(BaseModel):
    action_id: str
    description: str
    requires_approval: Literal[True] = True


class TriageReport(BaseModel):
    incident_id: str
    tool_trace: list[str]
    evidence: list[Evidence]
    hypotheses: list[Hypothesis]
    next_checks: list[str]
    proposed_actions: list[ProposedAction]

    @model_validator(mode="after")
    def validate_citation_boundary(self) -> TriageReport:
        allowed = {item.evidence_id for item in self.evidence}
        cited = {
            evidence_id
            for hypothesis in self.hypotheses
            for evidence_id in hypothesis.evidence_ids
        }
        unknown = sorted(cited - allowed)
        if unknown:
            raise ValueError(f"hypotheses cite unknown evidence IDs: {unknown}")
        return self


class ApprovalDecision(BaseModel):
    action_id: str
    approved: bool
    reason: str = Field(min_length=3, max_length=500)


class ApprovalRecord(ApprovalDecision):
    incident_id: str
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
