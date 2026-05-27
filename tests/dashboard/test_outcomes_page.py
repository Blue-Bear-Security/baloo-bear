from __future__ import annotations

from unittest.mock import AsyncMock, patch  # noqa: F401 – used by Task 6 tests below

from fastapi import FastAPI
from fastapi.testclient import TestClient  # noqa: F401 – used by Task 6 tests below

from baloo.dashboard.auth import verify_credentials
from baloo.dashboard.queries import DashboardService
from baloo.dashboard.router import router


def test_get_outcomes_data_method_exists():
    assert hasattr(DashboardService, "get_outcomes_data")
    assert callable(DashboardService.get_outcomes_data)


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_credentials] = lambda: "tester"
    return app


def test_outcomes_page_renders():
    app = _build_app()
    mock_data = {
        "total": 50,
        "outcomes": {"actioned": 20, "disputed": 5, "acknowledged": 10, "ignored": 15},
        "hit_rate": 60.0,
        "noise_rate": 40.0,
        "severity_data": {
            "HIGH": {"total": 20, "actioned": 15, "hit_rate": 75.0},
            "MEDIUM": {"total": 30, "actioned": 5, "hit_rate": 16.7},
        },
        "category_data": {
            "Security": {"total": 15, "actioned": 12, "hit_rate": 80.0},
            "Style": {"total": 20, "actioned": 2, "hit_rate": 10.0},
        },
        "trends": [
            {"day": "2026-04-27", "total": 168, "hit_rate": 83.3, "noise_rate": 16.7},
            {"day": "2026-04-28", "total": 61, "hit_rate": 77.0, "noise_rate": 23.0},
        ],
        "repos": ["owner/repo-a", "owner/repo-b"],
    }

    with patch(
        "baloo.dashboard.router.DashboardService.get_outcomes_data",
        new=AsyncMock(return_value=mock_data),
    ):
        client = TestClient(app)
        response = client.get("/dashboard/outcomes")

    assert response.status_code == 200
    assert "Outcomes" in response.text
    assert "60.0" in response.text  # hit_rate
    assert "Accuracy Over Time" in response.text
