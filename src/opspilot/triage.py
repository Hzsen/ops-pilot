from __future__ import annotations

import hashlib
from collections import defaultdict

from .domain import Evidence, Hypothesis, Incident, ProposedAction, TriageReport


LOG_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("dependency", ("connection refused", "connection reset", "upstream unavailable")),
    ("timeout", ("timeout", "timed out", "deadline exceeded")),
    ("memory", ("out of memory", "oomkilled", "oom killed")),
    ("server_error", ("status=500", "http 500", "status=502", "status=503")),
)

METRIC_RULES: dict[str, tuple[str, float]] = {
    "error_rate": ("high_error_rate", 0.05),
    "p95_latency_ms": ("latency", 1000.0),
    "cpu_percent": ("cpu", 90.0),
    "memory_percent": ("memory", 90.0),
    "queue_depth": ("queue", 1000.0),
}

RUNBOOKS: dict[str, str] = {
    "dependency": "Check upstream health, DNS, connection pools, and recent dependency deploys.",
    "timeout": "Compare stage timings with the latency budget and isolate the slow dependency.",
    "latency": "Inspect p95/p99 by endpoint and dependency before changing timeout values.",
    "memory": "Inspect working-set growth, recent allocations, and container memory limits.",
    "server_error": "Group 5xx responses by exception and correlate with the latest deployment.",
    "high_error_rate": "Break down errors by endpoint, status code, region, and deploy version.",
    "cpu": "Inspect hot endpoints, request volume, and CPU throttling before scaling.",
    "queue": "Compare arrival and processing rates, oldest message age, and worker health.",
}


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


class TriageEngine:
    """Deterministic evidence boundary used before any LLM integration."""

    def triage(self, incident: Incident) -> TriageReport:
        evidence: list[Evidence] = []
        categories: dict[str, list[str]] = defaultdict(list)
        tool_trace: list[str] = []

        if incident.logs:
            tool_trace.append("log_search")
            for index, line in enumerate(incident.logs):
                lowered = line.casefold()
                for category, patterns in LOG_PATTERNS:
                    if any(pattern in lowered for pattern in patterns):
                        item = Evidence(
                            evidence_id=_stable_id("log", f"{index}:{line}"),
                            source_type="log",
                            source_ref=f"logs[{index}]",
                            excerpt=line[:500],
                        )
                        evidence.append(item)
                        categories[category].append(item.evidence_id)
                        break

        if incident.metrics:
            tool_trace.append("metric_anomaly")
            for name, value in sorted(incident.metrics.items()):
                rule = METRIC_RULES.get(name)
                if rule is None:
                    continue
                category, threshold = rule
                if value >= threshold:
                    excerpt = f"{name}={value:g} (threshold={threshold:g})"
                    item = Evidence(
                        evidence_id=_stable_id("metric", excerpt),
                        source_type="metric",
                        source_ref=name,
                        excerpt=excerpt,
                    )
                    evidence.append(item)
                    categories[category].append(item.evidence_id)

        if categories:
            tool_trace.append("runbook_retrieval")
            for category in sorted(categories):
                excerpt = RUNBOOKS[category]
                item = Evidence(
                    evidence_id=_stable_id("runbook", f"{category}:{excerpt}"),
                    source_type="runbook",
                    source_ref=f"runbooks/{category}",
                    excerpt=excerpt,
                )
                evidence.append(item)
                categories[category].append(item.evidence_id)

        hypotheses = self._build_hypotheses(categories)
        actions = self._build_actions(categories)
        return TriageReport(
            incident_id=incident.incident_id,
            tool_trace=tool_trace,
            evidence=evidence,
            hypotheses=hypotheses,
            next_checks=self._next_checks(categories),
            proposed_actions=actions,
        )

    @staticmethod
    def _build_hypotheses(categories: dict[str, list[str]]) -> list[Hypothesis]:
        templates: tuple[tuple[str, str, float], ...] = (
            ("dependency", "Upstream dependency failure is contributing to the incident.", 0.88),
            ("timeout", "The request path is exceeding its latency budget.", 0.82),
            ("latency", "Observed tail latency is above the service threshold.", 0.78),
            ("memory", "Memory pressure may be destabilizing the service.", 0.86),
            ("server_error", "Server errors indicate an application or dependency failure.", 0.76),
            ("high_error_rate", "The service error rate is above the incident threshold.", 0.80),
            ("cpu", "CPU saturation may be limiting request processing.", 0.75),
            ("queue", "Queue growth indicates processing is falling behind arrivals.", 0.81),
        )
        hypotheses = [
            Hypothesis(statement=statement, confidence=confidence, evidence_ids=categories[key])
            for key, statement, confidence in templates
            if key in categories
        ]
        if not hypotheses:
            hypotheses.append(
                Hypothesis(
                    statement="Available evidence is insufficient for a supported diagnosis.",
                    confidence=0.20,
                    evidence_ids=[],
                )
            )
        return hypotheses

    @staticmethod
    def _next_checks(categories: dict[str, list[str]]) -> list[str]:
        checks: list[str] = []
        if "dependency" in categories or "timeout" in categories:
            checks.append("Compare upstream health and dependency latency with the incident window.")
        if "server_error" in categories or "high_error_rate" in categories:
            checks.append("Correlate error groups with the latest deploy and configuration changes.")
        if "memory" in categories or "cpu" in categories:
            checks.append("Inspect resource saturation, throttling, and workload changes.")
        if "queue" in categories:
            checks.append("Compare queue arrival rate, processing rate, and oldest-message age.")
        if not checks:
            checks.append("Collect a wider log window and endpoint-level latency/error metrics.")
        return checks

    @staticmethod
    def _build_actions(categories: dict[str, list[str]]) -> list[ProposedAction]:
        actions: list[ProposedAction] = []
        for category in sorted(categories):
            description = f"Open the {category} runbook and assign an owner for verification."
            actions.append(
                ProposedAction(
                    action_id=_stable_id("action", category),
                    description=description,
                )
            )
        return actions

