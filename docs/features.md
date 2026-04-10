# Features

Overview of Trainsight's capabilities.

## Dashboard Pages

### Today

Your daily training brief:
- **Training Signal**: Go / Modify / Rest recommendation based on recovery state and planned workout
- **Recovery Status**: HRV trend, sleep score, resting HR (from Oura Ring)
- **Upcoming Workouts**: Next 3 days from your training plan
- **Weekly Load**: This week's accumulated training stress vs plan

### Training

Multi-week training analysis:
- **Fitness/Fatigue Chart**: CTL (fitness), ATL (fatigue), TSB (form) over 60 days with 14-day projection
- **Training Diagnosis**: Volume trends, consistency, interval quality, zone distribution vs targets
- **Threshold Trend**: CP, LTHR, or threshold pace progression over time
- **Workout Flags**: Sessions flagged as notably better or worse than expected given recovery state
- **Weekly Compliance**: Actual vs planned load per week

### Goal

Race prediction and goal tracking:
- **Race Countdown**: Days to race, predicted vs target time
- **Threshold Gap**: Current CP/LTHR/pace vs what's needed for your goal
- **Milestones**: CP progression milestones with predicted race times
- **Feasibility Assessment**: Whether your goal is realistic given current trajectory

### Settings

Configuration management:
- **Connections**: Add/remove data sources (Garmin, Stryd, Oura)
- **Training Base**: Switch between power, HR, or pace
- **Thresholds**: Auto-detected or manual override for CP, LTHR, pace
- **Goal**: Race date, distance, target time
- **Science**: Choose training theories for each pillar

### Science

Browse and select training science theories:
- **4 Pillars**: Load model, recovery assessment, race prediction, zone framework
- **Theory Comparison**: Side-by-side descriptions with research citations
- **Recommendations**: System suggests theories based on your data and goals

## Training Metrics

### Fitness Tracking

- **CTL** (Chronic Training Load): 42-day exponentially weighted average of daily training stress. Represents fitness.
- **ATL** (Acute Training Load): 7-day exponentially weighted average. Represents fatigue.
- **TSB** (Training Stress Balance): CTL minus ATL. Positive = fresh, negative = fatigued.
- **RSS** (Running Stress Score): Power-based session load. Formula: (duration/3600) * (power/CP)^2 * 100
- **TRIMP**: HR-based load using Banister's exponential formula
- **rTSS**: Pace-based load using threshold pace ratio

### Training Diagnosis

Analyzes the last 6 weeks across 4 dimensions:
1. **Volume**: Weekly average km, trend direction
2. **Consistency**: Session count, longest gap, weeks with <3 sessions
3. **Interval Intensity**: Supra-threshold sessions (key driver of CP improvement), max/avg work power
4. **Zone Distribution**: Actual vs target percentage per zone, flagging deviations >5%

### Race Prediction

Two models:
- **Critical Power Model**: Uses Stryd race power fractions (5K: 103.8% CP, marathon: 89.9% CP) and power-to-pace regression
- **Riegel Formula**: T2 = T1 * (D2/D1)^1.06, pace-based extrapolation

### Recovery Analysis

Based on Kiviniemi and Plews HRV protocols:
- **HRV Status**: Today's HRV vs rolling baseline, trend direction, coefficient of variation
- **Sleep Score**: From Oura Ring
- **Resting HR**: Trend detection (elevated RHR signals fatigue)
- **Combined Status**: Fresh / Normal / Fatigued

## AI Features

### Training Plan Generation

AI generates personalized 4-week plans following:
- Target distribution from your active zone theory (defaults to ~80% easy / ~20% quality)
- 3 build + 1 recovery mesocycle
- Zone targets based on current threshold and selected zone framework
- Recovery-aware scheduling

Plans can be pushed to Stryd for watch integration.

### Science Framework

Swappable training theories backed by published research. Each theory is a YAML file with parameters, zone definitions, and citations. Users can switch theories to change how metrics are calculated.

## Data Sources

| Platform | Provides |
|----------|----------|
| Garmin Connect | Activities, splits, daily metrics (VO2max, RHR), lactate threshold |
| Stryd | Power data, running dynamics, CP estimates, training plan |
| Oura Ring | Sleep scores/stages, readiness, HRV, resting HR |
