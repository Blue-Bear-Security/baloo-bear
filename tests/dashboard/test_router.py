from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from baloo.dashboard.auth import verify_credentials
from baloo.dashboard.router import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_credentials] = lambda: "tester"
    return app


def test_dashboard_overview_renders() -> None:
    app = _build_app()
    stats = {
        "total_reviews": 12,
        "reviews_today": 3,
        "avg_duration": 14.2,
        "approval_rate": 75.0,
        "severity": {"MEDIUM": 2},
        "recent_reviews": [
            SimpleNamespace(
                id=1,
                repo_full_name="example-org/example-repo",
                pr_number=42,
                pr_title="Fix dashboard rendering",
                review_status="approved",
                duration_seconds=12.5,
                started_at=datetime(2026, 4, 14, 12, 0, tzinfo=timezone.utc),
            )
        ],
        "errors_total": 0,
        "errors_today": 0,
        "error_rate": 0.0,
        "error_categories": {},
        "recent_failures": [],
        "hourly_activity": [],
    }

    with patch(
        "baloo.dashboard.router.DashboardService.get_overview_stats",
        new=AsyncMock(return_value=stats),
    ):
        client = TestClient(app)
        response = client.get("/dashboard/")

    assert response.status_code == 200
    assert "Overview" in response.text
    assert "example-org/example-repo" in response.text


def test_dashboard_settings_renders_sanitized_values(monkeypatch) -> None:
    from baloo.config.settings import reset_settings

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://dbuser:dbpass@db.example.com:5432/baloo"
        "?sslmode=require&password=query-secret&sslpassword=ssl-secret",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-secret")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "dashboard-secret")
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    reset_settings()

    app = _build_app()
    client = TestClient(app)
    response = client.get("/dashboard/settings")

    assert response.status_code == 200
    assert "Settings" in response.text
    assert "APP_ENVIRONMENT" in response.text
    assert "production" in response.text
    assert "DATABASE_URL" in response.text
    assert (
        "postgresql+asyncpg://db.example.com:5432/baloo"
        "?sslmode=require&amp;password=%5BREDACTED%5D&amp;sslpassword=%5BREDACTED%5D"
        in response.text
    )
    assert "Configured (redacted)" in response.text
    assert "dbuser" not in response.text
    assert "dbpass" not in response.text
    assert "query-secret" not in response.text
    assert "ssl-secret" not in response.text
    assert "sk-ant-test-secret" not in response.text
    assert "webhook-secret" not in response.text
    assert "dashboard-secret" not in response.text
