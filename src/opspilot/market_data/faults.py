from __future__ import annotations

from datetime import datetime, timedelta

from .domain import FaultSpec, FaultType, MarketDataBatch, MarketDataFixture


class FaultInjectionError(ValueError):
    pass


class FaultInjector:
    """Apply explicit, deterministic faults to a known-clean fixture."""

    def inject(
        self, fixture: MarketDataFixture, faults: list[FaultSpec]
    ) -> MarketDataBatch:
        rows = [row.model_dump(mode="json") for row in fixture.rows]

        for fault in faults:
            index = self._target_index(rows, fixture, fault)
            if fault.fault_type == FaultType.MISSING_ROW:
                rows.pop(index)
            elif fault.fault_type == FaultType.DUPLICATE_ROW:
                rows.insert(index + 1, dict(rows[index]))
            elif fault.fault_type == FaultType.STALE_TIMESTAMP:
                current = datetime.fromisoformat(
                    str(rows[index]["timestamp"]).replace("Z", "+00:00")
                )
                rows[index]["timestamp"] = (current - timedelta(days=1)).isoformat()
            elif fault.fault_type == FaultType.INCORRECT_ADJUSTMENT:
                rows[index]["adjusted_close"] = round(
                    float(rows[index]["adjusted_close"]) * 1.1, 8
                )
            elif fault.fault_type == FaultType.SCHEMA_DRIFT:
                rows[index]["trade_volume"] = rows[index].pop("volume")
            else:  # pragma: no cover - enum validation makes this defensive only
                raise FaultInjectionError(f"unsupported fault: {fault.fault_type}")

        return MarketDataBatch(
            fixture_id=fixture.fixture_id,
            fixture_version=fixture.version,
            dataset=fixture.dataset,
            provider=fixture.provider,
            exchange=fixture.exchange,
            timezone=fixture.timezone,
            expected_symbols=fixture.expected_symbols,
            sessions=fixture.sessions,
            rows=rows,
            corporate_actions=fixture.corporate_actions,
            injected_faults=faults,
        )

    @staticmethod
    def _target_index(
        rows: list[dict], fixture: MarketDataFixture, fault: FaultSpec
    ) -> int:
        preferred_symbol = fault.symbol
        preferred_session = fault.session

        if fault.fault_type == FaultType.INCORRECT_ADJUSTMENT:
            if preferred_symbol is None or preferred_session is None:
                if not fixture.corporate_actions:
                    raise FaultInjectionError(
                        "incorrect_adjustment requires a fixture corporate action"
                    )
                action = fixture.corporate_actions[0]
                preferred_symbol = preferred_symbol or action.symbol
                preferred_session = preferred_session or action.ex_date
            action_keys = {
                (action.symbol, action.ex_date) for action in fixture.corporate_actions
            }
            if (preferred_symbol, preferred_session) not in action_keys:
                raise FaultInjectionError(
                    "incorrect_adjustment must target a fixture corporate action"
                )

        for index, row in enumerate(rows):
            if preferred_symbol is not None and row.get("symbol") != preferred_symbol:
                continue
            if preferred_session is not None and row.get("session") != preferred_session.isoformat():
                continue
            return index

        target = "/".join(
            value
            for value in (
                preferred_symbol,
                preferred_session.isoformat() if preferred_session else None,
            )
            if value
        )
        raise FaultInjectionError(f"fault target is not present in the fixture: {target}")
