from fastapi.testclient import TestClient

from opspilot.api import create_app


def test_market_data_fixture_and_triage_endpoints() -> None:
    client = TestClient(create_app())

    fixtures = client.get("/api/market-data/fixtures")
    assert fixtures.status_code == 200
    assert fixtures.json()[0]["fixture_id"] == "us-equity-daily-bars-v1"

    triaged = client.post(
        "/api/market-data/triage",
        json={
            "fixture_id": "us-equity-daily-bars-v1",
            "faults": [
                {
                    "fault_type": "missing_row",
                    "symbol": "AAA",
                    "session": "2025-01-02",
                }
            ],
        },
    )
    assert triaged.status_code == 200
    report = triaged.json()
    assert report["fixture_version"] == "1.0.0"
    assert "inspect_partition" in report["tool_trace"]
    assert report["proposed_actions"][0]["action_type"] == "dry_run_refetch"
    assert report["proposed_actions"][0]["requires_approval"] is True


def test_market_data_endpoint_rejects_an_invalid_fault_target() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/market-data/triage",
        json={
            "faults": [
                {
                    "fault_type": "incorrect_adjustment",
                    "symbol": "AAA",
                    "session": "2025-01-02",
                }
            ]
        },
    )

    assert response.status_code == 422
    assert "corporate action" in response.json()["detail"]
