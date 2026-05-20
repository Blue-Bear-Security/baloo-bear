"""Tests for the tenant filter helper."""

from sqlalchemy import select
from sqlalchemy.dialects import sqlite

from baloo.db.models import FeedbackSignal, FindingOutcome, Review
from baloo.db.tenant import apply_tenant_filter


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))


def test_apply_tenant_filter_adds_where_clause():
    stmt = select(Review)
    filtered = apply_tenant_filter(stmt, Review, "inst_abc")
    sql = _sql(filtered)
    assert "installation_id = 'inst_abc'" in sql


def test_apply_tenant_filter_no_op_when_none():
    stmt = select(Review)
    filtered = apply_tenant_filter(stmt, Review, None)
    sql = _sql(filtered)
    assert "WHERE" not in sql


def test_apply_tenant_filter_works_on_all_models():
    for model in [Review, FeedbackSignal, FindingOutcome]:
        stmt = select(model)
        filtered = apply_tenant_filter(stmt, model, "tenant_x")
        sql = _sql(filtered)
        assert "installation_id = 'tenant_x'" in sql, f"Filter missing for {model.__name__}"
