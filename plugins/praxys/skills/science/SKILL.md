---
name: science
description: >-
  Browse, compare, and select training science theories for Praxys. Covers
  4 pillars: load model (CTL/ATL/TSB), recovery assessment (HRV protocols),
  race prediction (power model vs Riegel), and zone framework (Coggan 5-zone
  vs Seiler polarized). Use this skill when the user asks "what zone theory
  should I use", "switch to polarized", "change load model", "browse science
  theories", "explain coggan vs seiler", "science configuration", "which
  prediction model", "change recovery theory", "what theories are available",
  or any request to understand or change the scientific models behind their
  training analysis.
---

# Praxys Science Framework

The science framework lets users choose which exercise science theories drive
their training analysis. Each pillar has multiple theories backed by published
research.

## How It Works

Theories are YAML files in `data/science/{pillar}/`. The user's active selection
is stored in their settings under the `science` key. Use the `get_settings` and
`update_settings` MCP tools to read and modify the active theories.

## Exploring Theories

Read the YAML files in `data/science/` to show available options:

```
data/science/
  load/           banister_pmc.yaml, banister_ultra.yaml
  recovery/       hrv_based.yaml
  prediction/     critical_power.yaml, riegel.yaml
  zones/          coggan_5zone.yaml, polarized_3zone.yaml
  labels/         standard.yaml, stryd.yaml
```

Each YAML contains: `name`, `simple_description`, `advanced_description`,
`citations`, and `params` (the numerical parameters used in computation).

When presenting theories:
1. Start with `simple_description` for accessibility
2. Show `advanced_description` if the user wants detail
3. Always mention citations so they can verify the science

## The Four Pillars

### 1. Load Model (CTL/ATL/TSB)

| Theory | Key Difference |
|--------|---------------|
| `banister_pmc` | Standard: CTL tau=42d, ATL tau=7d. Industry default. |
| `banister_ultra` | Different time constants tuned for ultra-distance training. |

**Affects:** Fitness (CTL), fatigue (ATL), form (TSB), daily training signal.

### 2. Recovery Assessment

| Theory | Key Difference |
|--------|---------------|
| `hrv_based` | Canonical ln(RMSSD) recovery model (Plews + Kiviniemi). Requires HRV data. |

### 3. Race Prediction

| Theory | Key Difference |
|--------|---------------|
| `critical_power` | Stryd model: power-to-pace with distance-specific power fractions. |
| `riegel` | Classic formula: T2 = T1 * (D2/D1)^1.06. Pace-based. |

**Recommendation:** `critical_power` with Stryd, `riegel` for pace-only.

### 4. Zone Framework

| Theory | Key Difference |
|--------|---------------|
| `coggan_5zone` | 5 zones: Recovery / Endurance / Tempo / Threshold / VO2max |
| `polarized_3zone` | 3 zones: Easy / No-man's-land / Hard (Seiler 80/20) |

## Changing a Theory

1. Call `get_settings` to see current active theories
2. Read the YAML for the new theory to confirm it's what the user wants
3. Call `update_settings` with the `science` dict, e.g.:
   ```json
   {"science": {"zones": "polarized_3zone"}}
   ```
4. If changing zone framework, also update `zones` boundaries from the
   theory's `params.boundaries`
