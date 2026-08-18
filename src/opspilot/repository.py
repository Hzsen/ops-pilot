from __future__ import annotations

from dataclasses import dataclass, field

from .domain import ApprovalRecord, Incident, IncidentStatus, TriageReport


class IncidentNotFoundError(KeyError):
    pass


@dataclass
class InMemoryIncidentRepository:
    incidents: dict[str, Incident] = field(default_factory=dict)
    reports: dict[str, TriageReport] = field(default_factory=dict)
    approvals: dict[str, list[ApprovalRecord]] = field(default_factory=dict)

    def create(self, incident: Incident) -> Incident:
        self.incidents[incident.incident_id] = incident
        return incident

    def get(self, incident_id: str) -> Incident:
        try:
            return self.incidents[incident_id]
        except KeyError as error:
            raise IncidentNotFoundError(incident_id) from error

    def save_report(self, report: TriageReport) -> TriageReport:
        incident = self.get(report.incident_id)
        self.reports[report.incident_id] = report
        self.incidents[report.incident_id] = incident.model_copy(
            update={"status": IncidentStatus.TRIAGED}
        )
        return report

    def get_report(self, incident_id: str) -> TriageReport:
        self.get(incident_id)
        try:
            return self.reports[incident_id]
        except KeyError as error:
            raise IncidentNotFoundError(f"triage report for {incident_id}") from error

    def record_approval(self, record: ApprovalRecord) -> ApprovalRecord:
        report = self.get_report(record.incident_id)
        allowed = {action.action_id for action in report.proposed_actions}
        if record.action_id not in allowed:
            raise ValueError("action_id is not present in the triage report")
        self.approvals.setdefault(record.incident_id, []).append(record)
        return record

