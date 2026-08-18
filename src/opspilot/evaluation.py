from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from .domain import Incident, IncidentCreate
from .triage import TriageEngine


class EvaluationCase(BaseModel):
    case_id: str
    incident: IncidentCreate
    expected_tools: list[str]
    expected_hypothesis_contains: str


def citation_integrity(report) -> bool:
    allowed = {item.evidence_id for item in report.evidence}
    return all(
        evidence_id in allowed
        for hypothesis in report.hypotheses
        for evidence_id in hypothesis.evidence_ids
    )


def run_suite(path: str | Path) -> dict:
    source = Path(path)
    cases = [EvaluationCase.model_validate(item) for item in json.loads(source.read_text())]
    engine = TriageEngine()
    details: list[dict] = []

    for case in cases:
        incident = Incident(incident_id=str(uuid4()), **case.incident.model_dump())
        report = engine.triage(incident)
        routed = set(case.expected_tools).issubset(report.tool_trace)
        hypothesis_match = any(
            case.expected_hypothesis_contains.casefold() in hypothesis.statement.casefold()
            for hypothesis in report.hypotheses
        )
        citations_valid = citation_integrity(report)
        passed = routed and hypothesis_match and citations_valid
        details.append(
            {
                "case_id": case.case_id,
                "passed": passed,
                "tool_routing": routed,
                "hypothesis_match": hypothesis_match,
                "citation_integrity": citations_valid,
            }
        )

    total = len(details)
    passed_count = sum(item["passed"] for item in details)
    return {
        "case_count": total,
        "passed_count": passed_count,
        "pass_rate": passed_count / total if total else 0.0,
        "tool_routing_accuracy": sum(item["tool_routing"] for item in details) / total,
        "hypothesis_match_rate": sum(item["hypothesis_match"] for item in details) / total,
        "citation_integrity_rate": sum(item["citation_integrity"] for item in details) / total,
        "cases": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the OpsPilot offline eval suite")
    parser.add_argument("dataset", nargs="?", default="eval/cases.json")
    args = parser.parse_args()
    result = run_suite(args.dataset)
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["passed_count"] == result["case_count"] else 1)


if __name__ == "__main__":
    main()

