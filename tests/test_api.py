from fastapi.testclient import TestClient

from opspilot.api import create_app


def test_incident_triage_and_approval_audit() -> None:
    client = TestClient(create_app())

    created = client.post(
        "/api/incidents",
        json={
            "title": "Checkout latency spike",
            "service": "checkout-api",
            "logs": ["payment upstream connection refused"],
            "metrics": {"p95_latency_ms": 1800},
        },
    )
    assert created.status_code == 201
    incident_id = created.json()["incident_id"]

    triaged = client.post(f"/api/incidents/{incident_id}/triage")
    assert triaged.status_code == 200
    report = triaged.json()
    assert report["proposed_actions"]
    assert all(item["requires_approval"] for item in report["proposed_actions"])

    action_id = report["proposed_actions"][0]["action_id"]
    approval = client.post(
        f"/api/incidents/{incident_id}/approvals",
        json={
            "action_id": action_id,
            "approved": False,
            "reason": "Need dependency-owner confirmation first.",
        },
    )
    assert approval.status_code == 200
    assert approval.json()["approved"] is False

    fetched = client.get(f"/api/incidents/{incident_id}")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "triaged"


def test_incident_requires_logs_or_metrics() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/incidents",
        json={"title": "No evidence", "service": "api", "logs": [], "metrics": {}},
    )
    assert response.status_code == 422

