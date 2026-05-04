# Outcomes Page: Daily Accuracy Chart

**Date:** 2026-05-04

## Problem

The Weekly Trends chart on the outcomes page is non-functional in practice. All existing outcome data falls within a single ISO week (2026-18), so the chart renders as a single dot with no trend visible. Weekly granularity won't become useful until many weeks of data accumulate.

Daily data has 6 distinct days with meaningful variation in hit/noise rates, making daily granularity immediately actionable.

## Decision

Replace the Weekly Trends chart with an Accuracy Over Time chart at daily granularity. The weekly query in `get_outcomes_data` is swapped for a daily one. No new charts are added — it's a direct replacement.

## Changes

### Backend: `baloo/dashboard/queries.py`

In `get_outcomes_data`, replace the weekly query block with a daily equivalent:

- Group by `DATE(labeled_at)` (dialect-agnostic — SQLite and Postgres both support `DATE()`)
- Aggregate outcomes per day into `daily_map` (same structure as `week_map`)
- Each entry in `trends`: `{"day": "YYYY-MM-DD", "total": N, "hit_rate": X, "noise_rate": Y}`
- Return key stays `trends` — no signature change

### Frontend: `baloo/dashboard/templates/outcomes.html`

- Chart title: "Weekly Trends" → "Accuracy Over Time"
- X-axis labels: `t.week` → `t.day`
- No other chart config changes

### Tests: `tests/dashboard/test_outcomes_page.py`

- Update mock `trends` entries to use `day` key instead of `week`

## Out of Scope

- Weekly trends chart is removed, not kept alongside. Can be re-added once months of data exist.
- No changes to summary cards, severity/category charts, or outcome distribution.
