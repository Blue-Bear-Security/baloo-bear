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
