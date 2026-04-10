---
name: science
description: >-
  Browse, compare, and select training science theories for Trainsight. Covers
  4 pillars: load model (CTL/ATL/TSB), recovery assessment (HRV protocols),
  race prediction (power model vs Riegel), and zone framework (Coggan 5-zone
  vs Seiler polarized). Use this skill when the user asks "what zone theory
  should I use", "switch to polarized", "change load model", "browse science
  theories", "explain coggan vs seiler", "science configuration", "which
  prediction model", "change recovery theory", "what theories are available",
  or any request to understand or change the scientific models behind their
  training analysis.
---

# Trainsight Science Framework

The science framework lets users choose which exercise science theories drive
their training analysis. Each pillar has multiple theories backed by published
research.

## How It Works

Theories are YAML files in `data/science/{pillar}/`. The user's active selection
is stored in `data/config.json` → `science` key:

```json
"science": {
  "load": "banister_pmc",
  "recovery": "composite",
  "prediction": "critical_power",
  "zones": "coggan_5zone"
}
```

## Exploring Theories

To show available theories, read the YAML files in each pillar directory:

```
data/science/
  load/           → banister_pmc.yaml, banister_ultra.yaml
  recovery/       → hrv_weighted.yaml, composite.yaml
  prediction/     → critical_power.yaml, riegel.yaml
  zones/          → coggan_5zone.yaml, polarized_3zone.yaml
  labels/         → standard.yaml, stryd.yaml
```

Each YAML file contains:
- `name` — display name
- `simple_description` — plain-language explanation for non-experts
- `advanced_description` — detailed technical explanation with tables/formulas
- `citations` — research papers backing the theory
- `params` — the actual numerical parameters used in computation

When presenting theories to the user:
1. Start with `simple_description` for accessibility
2. Show `advanced_description` if the user wants details
3. Always mention citations so the user can verify

## The Four Pillars

### 1. Load Model (CTL/ATL/TSB)

Controls how training load and fitness/fatigue are calculated.

| Theory | Key Difference |
|--------|---------------|
| `banister_pmc` | Standard: CTL tau=42d, ATL tau=7d. Industry default. |
| `banister_ultra` | Different time constants tuned for ultra-distance training. |

**Affects:** Fitness (CTL), fatigue (ATL), form (TSB), daily training signal,
TSB zone colors on the fitness chart.

### 2. Recovery Assessment

Controls how HRV, sleep, and resting HR are weighted in recovery analysis.

| Theory | Key Difference |
|--------|---------------|
| `hrv_weighted` | HRV-primary (Kiviniemi protocol). Ignores sleep/RHR modification. |
| `composite` | HRV + sleep + RHR combined (Plews protocol with practical weighting). |

**Affects:** Recovery status (Fresh/Normal/Fatigued), daily training signal,
workout modification recommendations.

**Recommendation:** Use `composite` if the user has Oura Ring (sleep + HRV).
Use `hrv_weighted` if they only have HRV data.

### 3. Race Prediction

Controls how race finish times are predicted.

| Theory | Key Difference |
|--------|---------------|
| `critical_power` | Stryd model: power-to-pace with distance-specific power fractions. |
| `riegel` | Classic formula: T2 = T1 * (D2/D1)^1.06. Pace-based. |

**Affects:** Predicted race times, goal feasibility, required CP/pace calculations.

**Recommendation:** Use `critical_power` if the user trains with power (has Stryd).
Use `riegel` if they train with pace only.

### 4. Zone Framework

Controls how training intensity zones are defined and how distribution is analyzed.

| Theory | Key Difference |
|--------|---------------|
| `coggan_5zone` | 5 zones: Recovery / Endurance / Tempo / Threshold / VO2max |
| `polarized_3zone` | 3 zones: Easy / No-man's-land / Hard (Seiler model) |

**Affects:** Zone boundaries, zone names, target distribution in diagnosis,
distribution bar in training review.

**Recommendation:** `coggan_5zone` for structured training with varied intensities.
`polarized_3zone` for athletes following strict polarized training (80/20).

### 5. Zone Labels (Cosmetic)

Controls the display names for TSB zones on the fitness chart. Does not affect
any math — purely cosmetic.

| Label Set | Style |
|-----------|-------|
| `standard` | Generic zone names |
| `stryd` | Stryd-branded zone names |

Set via `data/config.json` → `zone_labels`.

## Changing a Theory

1. Read the current config: `data/config.json` → `science`
2. Read the YAML for the new theory to confirm it's what the user wants
3. Update the relevant pillar in `data/config.json` → `science`
4. If changing zone framework, also update `zones` boundaries in config to match
   the new theory's `params.boundaries` (read from the YAML)

Example — switching from Coggan 5-zone to Seiler Polarized:
```json
"science": { "zones": "polarized_3zone" }
"zones": {
  "power": [0.80, 1.00],  // from the polarized_3zone.yaml params
  "hr": [0.85, 0.95],
  "pace": [1.10, 1.00]
}
```

## Making Recommendations

When the user asks which theory to use, consider:
- **Data availability:** power meter → power-based theories; HR only → HR-based
- **Training philosophy:** structured intervals → Coggan; strict 80/20 → Seiler
- **Race goals:** specific race → critical_power prediction; general fitness → either
- **Recovery data:** Oura Ring → composite recovery; HRV watch only → hrv_weighted

Present the tradeoffs clearly and let the user decide. Reference the citations
in the YAML files so they can read the original research.

## Code Reference

- `analysis/science.py` — `load_active_science()`, `get_available_theories()`, `Theory` dataclass
- `data/config.json` → `science` key (active selections) + `zone_labels`
- `data/science/{pillar}/*.yaml` — theory definitions
