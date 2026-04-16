"""Dashboard routes served with Jinja2 + HTMX."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from baloo.dashboard.auth import verify_credentials
from baloo.dashboard.queries import DashboardService

router = APIRouter(
    prefix="/dashboard",
    dependencies=[Depends(verify_credentials)],
)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


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
