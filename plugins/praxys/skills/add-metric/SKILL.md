---
name: add-metric
description: >-
  Scaffold a new training metric end-to-end. Use when adding a new computed
  metric, prediction, or insight to the dashboard. Guides through all 7 steps:
  pure function, data layer, API route, TypeScript type, React component, page
  integration, and test.
---

# Add Metric

Walk through each step below. Do not skip steps. Mark each complete before
moving to the next.

## Step 1: Pure Function in `analysis/metrics.py`

Write the metric as a **pure function** -- no I/O, no side effects.

Requirements:
- Type hints on all parameters and return value
- Docstring explaining what the metric measures and citing the source
- Citation comment for any formula, constant, or algorithm used
- Flag any estimates with `# ESTIMATE --` prefix

```python
def compute_example_metric(activities: pd.DataFrame, ...) -> dict:
    """Compute X metric using Y method.

    Based on Author (Year), doi:XX.XXXX/...
    """
```

If the metric uses split-level data (per-interval power, not diluted activity
averages), query the `activity_splits` DB table. See the "Critical: Split-Level
Power Analysis" section in CLAUDE.md.

## Step 2: Wire into `api/deps.py`

Call the function from `get_dashboard_data()` and add the result to the
returned dict:

```python
result["new_metric"] = compute_example_metric(data["activities"], ...)
```

If the metric needs a shared view helper (used by both API and CLI skills),
add it to `api/views.py` instead of duplicating extraction logic.

## Step 3: API Route in `api/routes/`

Add to an existing route file or create a new one. Routes must be thin
wrappers -- no business logic.

If creating a new route file:
1. Create `api/routes/{name}.py` with a FastAPI `APIRouter`
2. Register it in `api/routes/__init__.py`
3. Mount it in `api/main.py`

## Step 4: TypeScript Type in `web/src/types/api.ts`

Add an interface matching the JSON shape returned by the API:

```typescript
export interface ExampleMetric {
  value: number;
  trend: "up" | "down" | "stable";
  // ...
}
```

## Step 5: React Component in `web/src/components/`

Build the UI component following the design system:
- Wrap in a shadcn `Card` with `CardHeader` + `CardContent`
- Use `font-data` class for all numeric values
- Import chart colors from `@/lib/chart-theme.ts` (no raw hex)
- Use `Skeleton` for loading states (never "Loading..." text)
- Add a `ScienceNote` component showing how the metric is calculated

## Step 6: Add to Page in `web/src/pages/`

Import the component and add it to the appropriate page. Use the responsive
grid pattern: `grid-cols-1 lg:grid-cols-2`.

## Step 7: Test in `tests/`

Add a test file or extend an existing one:
- Test the pure function with known inputs and expected outputs
- Test edge cases (empty data, missing columns, zero values)
- If the metric has a formula, verify against a hand-calculated example

```bash
python -m pytest tests/test_metrics.py -v -k "test_new_metric"
```

## After All Steps

Run the full test suite to check for regressions:

```bash
python -m pytest tests/ -v
```

Then update CLAUDE.md if the metric changes the architecture (new route file,
new data source, etc.).
