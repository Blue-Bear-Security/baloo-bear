# Outcomes Daily Accuracy Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the non-functional Weekly Trends line chart on the outcomes page with a daily Accuracy Over Time chart.

**Architecture:** The weekly grouping query in `get_outcomes_data` is replaced with a daily one using `DATE(labeled_at)`, which is dialect-agnostic. The return key `trends` is unchanged; each entry's `week` field becomes `day`. The template swaps the chart title and x-axis label accessor.

**Tech Stack:** Python/SQLAlchemy (backend), Jinja2 + Chart.js 4 (frontend), pytest (tests)

**Worktree:** `.worktrees/fix/outcomes-daily-accuracy`

---

### Task 1: Update tests to reflect daily data shape

**Files:**
- Modify: `tests/dashboard/test_outcomes_page.py`

- [ ] **Step 1: Update mock trends data and add title assertion**

In `test_outcomes_page_renders`, change the `trends` entries from `week` keys to `day` keys, and add an assertion that the new chart title appears:

```python
"trends": [
    {"day": "2026-04-27", "total": 168, "hit_rate": 83.3, "noise_rate": 16.7},
    {"day": "2026-04-28", "total": 61,  "hit_rate": 77.0, "noise_rate": 23.0},
],
```

And at the end of the test, add:

```python
assert "Accuracy Over Time" in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd .worktrees/fix/outcomes-daily-accuracy
uv run pytest tests/dashboard/test_outcomes_page.py -v
```

Expected: `test_outcomes_page_renders` FAILS — `"Accuracy Over Time"` not in response (template still says "Weekly Trends").

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/dashboard/test_outcomes_page.py
git commit -m "test: update outcomes mock data to use daily trends shape"
```

---

### Task 2: Replace weekly query with daily query in backend

**Files:**
- Modify: `baloo/dashboard/queries.py` (lines 483–529)

- [ ] **Step 1: Replace the weekly trends block**

Find the comment `# --- Weekly trends (dialect-aware) ---` and replace everything from that comment through the `trends = [...]` list comprehension with:

```python
# --- Daily accuracy trends ---
daily_rows = (
    await session.execute(
        select(
            func.date(FindingOutcome.labeled_at).label("day"),
            FindingOutcome.outcome,
            func.count(FindingOutcome.id),
        )
        .where(*_base_filters())
        .group_by("day", FindingOutcome.outcome)
        .order_by("day")
    )
).all()

day_map: dict[str, dict] = {}
for day, outcome, cnt in daily_rows:
    day_key = str(day)
    if day_key not in day_map:
        day_map[day_key] = {
            "total": 0,
            "actioned": 0,
            "acknowledged": 0,
            "disputed": 0,
            "ignored": 0,
        }
    day_map[day_key]["total"] += cnt
    if outcome in day_map[day_key]:
        day_map[day_key][outcome] += cnt
trends = [
    {
        "day": d,
        "total": v["total"],
        "hit_rate": round(v["actioned"] / v["total"] * 100, 1) if v["total"] else 0.0,
        "noise_rate": (
            round((v["disputed"] + v["ignored"]) / v["total"] * 100, 1)
            if v["total"]
            else 0.0
        ),
    }
    for d, v in day_map.items()
]
```

- [ ] **Step 2: Run tests — still failing (template not updated yet)**

```bash
uv run pytest tests/dashboard/test_outcomes_page.py -v
```

Expected: still FAIL on `"Accuracy Over Time"` assertion.

- [ ] **Step 3: Commit**

```bash
git add baloo/dashboard/queries.py
git commit -m "feat: switch outcomes trends query from weekly to daily granularity"
```

---

### Task 3: Update template

**Files:**
- Modify: `baloo/dashboard/templates/outcomes.html` (lines 73, 159)

- [ ] **Step 1: Update chart title**

Change line 73:
```html
    <h2 class="text-lg font-semibold text-gray-900 mb-4">Weekly Trends</h2>
```
to:
```html
    <h2 class="text-lg font-semibold text-gray-900 mb-4">Accuracy Over Time</h2>
```

- [ ] **Step 2: Update x-axis label accessor**

Change line 159:
```javascript
      labels: trends.map(t => t.week),
```
to:
```javascript
      labels: trends.map(t => t.day),
```

- [ ] **Step 3: Run tests — should now pass**

```bash
uv run pytest tests/dashboard/test_outcomes_page.py -v
```

Expected: 2 passed.

- [ ] **Step 4: Run full test suite**

```bash
uv run pytest --tb=short -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add baloo/dashboard/templates/outcomes.html
git commit -m "feat: replace Weekly Trends chart with daily Accuracy Over Time"
```
