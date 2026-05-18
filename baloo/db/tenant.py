"""Tenant isolation helper for multi-tenant DB queries."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select


def apply_tenant_filter(stmt: Select, model: Any, installation_id: str | None) -> Select:
    """Append WHERE installation_id = ? if installation_id is set; no-op otherwise."""
    if installation_id:
        return stmt.where(model.installation_id == installation_id)
    return stmt
