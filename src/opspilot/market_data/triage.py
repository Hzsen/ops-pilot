from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import date

from ..domain import Evidence, Hypothesis
from .domain import (
    FindingCategory,
    MarketDataBatch,
    MarketDataProposedAction,
    MarketDataTriageReport,
    QuarantineArguments,
    RebuildArguments,
    RefetchArguments,
    ToolFinding,
)
from .tools import CorporateActionTool, DataProfileTool, TradingCalendarTool


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


FAULT_CATEGORIES = {
    FindingCategory.MISSING_ROW,
    FindingCategory.DUPLICATE_ROW,
    FindingCategory.STALE_TIMESTAMP,
    FindingCategory.INCORRECT_ADJUSTMENT,
    FindingCategory.SCHEMA_DRIFT,
}


class MarketDataTriageEngine:
    """Orchestrate read-only, typed tools over a deterministic fixture batch."""

    def __init__(self) -> None:
        self.data_profile = DataProfileTool()
        self.calendar = TradingCalendarTool()
        self.corporate_actions = CorporateActionTool()

    def triage(self, batch: MarketDataBatch) -> MarketDataTriageReport:
        results = [self.data_profile.run(batch), self.calendar.run(batch)]
        profile_findings = results[0].findings
        adjustment_findings = [
            finding
            for finding in profile_findings
            if finding.category == FindingCategory.INCORRECT_ADJUSTMENT
        ]
        if adjustment_findings:
            symbols = {
                symbol
                for finding in adjustment_findings
                for symbol in finding.affected_symbols
            }
            sessions = {
                session
                for finding in adjustment_findings
                for session in finding.affected_sessions
            }
            results.append(self.corporate_actions.run(batch, symbols, sessions))

        findings = [finding for result in results for finding in result.findings]
        evidence = [self._to_evidence(finding) for finding in findings]
        categories: dict[FindingCategory, list[str]] = defaultdict(list)
        for finding in findings:
            categories[finding.category].append(finding.finding_id)

        if FindingCategory.INCORRECT_ADJUSTMENT in categories:
            categories[FindingCategory.INCORRECT_ADJUSTMENT].extend(
                categories.get(FindingCategory.CORPORATE_ACTION, [])
            )

        fault_findings = [finding for finding in findings if finding.category in FAULT_CATEGORIES]
        return MarketDataTriageReport(
            fixture_id=batch.fixture_id,
            fixture_version=batch.fixture_version,
            dataset=batch.dataset,
            injected_faults=batch.injected_faults,
            tool_trace=[result.tool_name for result in results],
            evidence=evidence,
            hypotheses=self._build_hypotheses(categories),
            next_checks=self._next_checks(categories),
            proposed_actions=self._build_actions(batch, fault_findings),
        )

    @staticmethod
    def _to_evidence(finding: ToolFinding) -> Evidence:
        return Evidence(
            evidence_id=finding.finding_id,
            source_type=finding.source_type,
            source_ref=finding.source_ref,
            excerpt=finding.excerpt,
        )

    @staticmethod
    def _build_hypotheses(
        categories: dict[FindingCategory, list[str]],
    ) -> list[Hypothesis]:
        templates = (
            (
                FindingCategory.MISSING_ROW,
                "The partition is incomplete for one or more expected symbol/session keys.",
                0.98,
            ),
            (
                FindingCategory.DUPLICATE_ROW,
                "The partition contains duplicate symbol/session keys.",
                0.99,
            ),
            (
                FindingCategory.STALE_TIMESTAMP,
                "At least one bar timestamp does not belong to its declared trading session.",
                0.97,
            ),
            (
                FindingCategory.INCORRECT_ADJUSTMENT,
                "Adjusted prices are inconsistent with the recorded adjustment factor.",
                0.96,
            ),
            (
                FindingCategory.SCHEMA_DRIFT,
                "One or more rows violate the allowlisted daily-bar schema.",
                0.99,
            ),
        )
        hypotheses = [
            Hypothesis(statement=statement, confidence=confidence, evidence_ids=categories[key])
            for key, statement, confidence in templates
            if key in categories
        ]
        if not hypotheses:
            hypotheses.append(
                Hypothesis(
                    statement="No supported data-quality fault was found in this fixture batch.",
                    confidence=0.95,
                    evidence_ids=categories.get(FindingCategory.CLEAN_PROFILE, []),
                )
            )
        return hypotheses

    @staticmethod
    def _next_checks(categories: dict[FindingCategory, list[str]]) -> list[str]:
        checks: list[str] = []
        if FindingCategory.MISSING_ROW in categories:
            checks.append("Compare provider counts with the expected symbol/session matrix.")
        if FindingCategory.DUPLICATE_ROW in categories:
            checks.append("Inspect ingestion idempotency keys and merge semantics.")
        if FindingCategory.STALE_TIMESTAMP in categories:
            checks.append("Verify provider timezone conversion and exchange-session mapping.")
        if FindingCategory.INCORRECT_ADJUSTMENT in categories:
            checks.append("Reconcile the stored factor with the cited corporate-action record.")
        if FindingCategory.SCHEMA_DRIFT in categories:
            checks.append("Compare the provider payload schema with the allowlisted contract.")
        if not checks:
            checks.append("No recovery check is needed; retain the fixture result as a baseline.")
        return checks

    @classmethod
    def _build_actions(
        cls, batch: MarketDataBatch, findings: list[ToolFinding]
    ) -> list[MarketDataProposedAction]:
        by_category: dict[FindingCategory, list[ToolFinding]] = defaultdict(list)
        for finding in findings:
            by_category[finding.category].append(finding)

        actions: list[MarketDataProposedAction] = []
        if FindingCategory.MISSING_ROW in by_category:
            affected = by_category[FindingCategory.MISSING_ROW]
            symbols, sessions = cls._scope(affected, batch)
            arguments = RefetchArguments(
                provider=batch.provider,
                dataset=batch.dataset,
                symbols=symbols,
                start=min(sessions),
                end=max(sessions),
            )
            actions.append(
                cls._action(
                    action_type="dry_run_refetch",
                    description="Prepare a bounded refetch preview for the missing rows.",
                    arguments=arguments,
                )
            )

        quarantine_categories = {
            FindingCategory.DUPLICATE_ROW,
            FindingCategory.STALE_TIMESTAMP,
            FindingCategory.SCHEMA_DRIFT,
        }
        quarantine_findings = [
            finding
            for category in quarantine_categories
            for finding in by_category.get(category, [])
        ]
        if quarantine_findings:
            _, sessions = cls._scope(quarantine_findings, batch)
            start, end = min(sessions), max(sessions)
            partition = f"session={start.isoformat()}"
            if end != start:
                partition = f"sessions={start.isoformat()}..{end.isoformat()}"
            arguments = QuarantineArguments(
                dataset=batch.dataset,
                partition=partition,
                reason="; ".join(sorted({item.category.value for item in quarantine_findings})),
            )
            actions.append(
                cls._action(
                    action_type="quarantine_partition",
                    description="Prepare a quarantine preview for the affected partition.",
                    arguments=arguments,
                )
            )

        if FindingCategory.INCORRECT_ADJUSTMENT in by_category:
            affected = by_category[FindingCategory.INCORRECT_ADJUSTMENT]
            symbols, sessions = cls._scope(affected, batch)
            start, end = min(sessions), max(sessions)
            partition = f"session={start.isoformat()}"
            if end != start:
                partition = f"sessions={start.isoformat()}..{end.isoformat()}"
            arguments = RebuildArguments(
                dataset=batch.dataset,
                partition=partition,
                symbols=symbols,
            )
            actions.append(
                cls._action(
                    action_type="rebuild_adjustments",
                    description="Prepare an adjustment-rebuild preview for the affected rows.",
                    arguments=arguments,
                )
            )
        return actions

    @staticmethod
    def _scope(
        findings: list[ToolFinding], batch: MarketDataBatch
    ) -> tuple[list[str], list[date]]:
        symbols = sorted(
            {symbol for finding in findings for symbol in finding.affected_symbols}
        ) or sorted(batch.expected_symbols)
        sessions = sorted(
            {session for finding in findings for session in finding.affected_sessions}
        ) or sorted(batch.sessions)
        return symbols, sessions

    @staticmethod
    def _action(*, action_type: str, description: str, arguments):
        payload = arguments.model_dump_json()
        identity = f"{action_type}:{payload}"
        return MarketDataProposedAction(
            action_id=_stable_id("action", identity),
            action_type=action_type,
            description=description,
            arguments=arguments,
            idempotency_key=_stable_id("idem", identity),
        )
