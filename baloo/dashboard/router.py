"""Dashboard routes served with Jinja2 + HTMX."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from baloo.config.settings import Settings, get_settings
from baloo.dashboard.auth import verify_credentials
from baloo.dashboard.queries import DashboardService

router = APIRouter(
    prefix="/dashboard",
    dependencies=[Depends(verify_credentials)],
)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

SENSITIVE_SETTINGS = {
    "anthropic_api_key",
    "dashboard_password",
    "github_private_key",
    "github_webhook_secret",
}

SENSITIVE_DATABASE_QUERY_KEYS = {
    "api_key",
    "apikey",
    "auth_source",
    "authsource",
    "client_secret",
    "pass",
    "password",
    "pwd",
    "secret",
    "ssl_password",
    "sslpassword",
    "token",
}

SETTING_CATEGORIES = {
    "GitHub": {
        "github_app_id",
        "github_private_key",
        "github_webhook_secret",
        "webhook_pre_verified",
    },
    "Anthropic": {"anthropic_api_key"},
    "Application": {
        "app_environment",
        "app_host",
        "app_port",
        "log_level",
        "max_concurrent_reviews",
        "review_stale_timeout_minutes",
    },
    "Agent": {
        "agent_provider",
        "agent_model",
        "agent_fallback_model",
        "agent_max_tokens",
        "agent_temperature",
        "pi_binary_path",
        "pi_thinking_level",
    },
    "Review": {
        "ticket_id_prefix",
        "review_auto_approve",
        "review_min_severity",
        "review_use_checks_api",
    },
    "Database": {"database_url", "database_enabled", "installation_id"},
    "Dashboard": {
        "dashboard_enabled",
        "dashboard_username",
        "dashboard_password",
        "log_retention_days",
    },
    "False-Positive Verification": {
        "fp_verification_enabled",
        "fp_verification_model",
        "fp_verification_max_concurrent",
        "fp_audit_log_path",
    },
    "Thread Agent": {
        "thread_agent_enabled",
        "thread_agent_model",
        "thread_agent_max_replies",
        "thread_agent_max_concurrent",
    },
    "Feedback Signals": {"feedback_signals_enabled", "feedback_signals_ttl_days"},
    "AST Tools": {"ast_tools_enabled"},
    "Fidelity Report": {
        "fidelity_enabled",
        "fidelity_plan_path_pattern",
        "fidelity_approval_threshold",
    },
    "Repo Provisioning": {
        "repo_cache_enabled",
        "repo_cache_root",
        "repo_cache_max_disk_gb",
        "repo_sandbox_mode",
    },
}


def _sanitize_database_query(query: str) -> str:
    if not query:
        return ""

    params = parse_qsl(query, keep_blank_values=True)
    sanitized = [
        (key, "[REDACTED]" if key.lower() in SENSITIVE_DATABASE_QUERY_KEYS else value)
        for key, value in params
    ]
    return urlencode(sanitized, doseq=True)


def _sanitize_database_url(value: str) -> str:
    """Remove database credentials while preserving the useful connection target."""
    if not value:
        return "(empty)"

    try:
        parsed = urlsplit(value)
    except ValueError:
        return "Configured (credentials redacted)"

    query = _sanitize_database_query(parsed.query)

    if not parsed.username and not parsed.password:
        if query == parsed.query:
            return value
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))

    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is not None:
        host = f"{host}:{port}"
    return urlunsplit((parsed.scheme, host, parsed.path, query, parsed.fragment))


def _format_setting_value(name: str, value: Any) -> str:
    if name in SENSITIVE_SETTINGS:
        return "Configured (redacted)" if value else "Not configured"
    if name == "database_url":
        return _sanitize_database_url(str(value or ""))
    if value is None:
        return "None"
    if value == "":
        return "(empty)"
    return str(value)


def _setting_category(name: str) -> str:
    for category, names in SETTING_CATEGORIES.items():
        if name in names:
            return category
    return "Other"


def _settings_rows() -> list[dict[str, str]]:
    settings = get_settings()
    rows = []
    for name, field in Settings.model_fields.items():
        value = getattr(settings, name)
        default = field.default
        rows.append(
            {
                "category": _setting_category(name),
                "env_var": name.upper(),
                "name": name,
                "value": _format_setting_value(name, value),
                "default": _format_setting_value(name, default),
                "description": field.description or "",
            }
        )
    return rows


@router.get("/", response_class=HTMLResponse)
async def overview(request: Request):
    stats = await DashboardService.get_overview_stats()
    return templates.TemplateResponse(
        request=request,
        name="overview.html",
        context=stats,
    )


@router.get("/reviews", response_class=HTMLResponse)
async def reviews_list(
    request: Request,
    page: int = Query(1, ge=1),
    repo: str | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None),
):
    data = await DashboardService.list_reviews(
        page=page,
        repo_filter=repo,
        status_filter=status,
        search_filter=search,
    )
    ctx = {"repo": repo, "status": status, "search": search, **data}
    # HTMX partial swap
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request=request,
            name="partials/reviews_table.html",
            context=ctx,
        )
    return templates.TemplateResponse(
        request=request,
        name="reviews.html",
        context=ctx,
    )


@router.get("/reviews/{review_id}", response_class=HTMLResponse)
async def review_detail(request: Request, review_id: int):
    review = await DashboardService.get_review_detail(review_id)
    if review is None:
        return HTMLResponse("<h1>Review not found</h1>", status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="review_detail.html",
        context={"review": review},
    )


@router.get("/reviews/{review_id}/logs", response_class=HTMLResponse)
async def review_logs(request: Request, review_id: int):
    logs = await DashboardService.get_review_logs(review_id)
    return templates.TemplateResponse(
        request=request,
        name="partials/review_logs.html",
        context={"logs": logs, "review_id": review_id},
    )


@router.get("/analytics", response_class=HTMLResponse)
async def analytics(
    request: Request,
    days: int = Query(30, ge=1, le=365),
):
    data = await DashboardService.get_analytics_data(days=days)
    return templates.TemplateResponse(
        request=request,
        name="analytics.html",
        context={"days": days, **data},
    )


@router.get("/outcomes", response_class=HTMLResponse)
async def outcomes(
    request: Request,
    days: int = Query(90, ge=1, le=365),
    repo: str | None = Query(None),
):
    data = await DashboardService.get_outcomes_data(days=days, repo_filter=repo)
    return templates.TemplateResponse(
        request=request,
        name="outcomes.html",
        context={"days": days, "repo": repo, **data},
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={"settings_rows": _settings_rows()},
    )
