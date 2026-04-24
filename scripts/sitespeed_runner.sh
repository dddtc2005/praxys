#!/usr/bin/env bash
# Run sitespeed.io for one or more baseline cells (scenario × device) against
# a target URL. Writes outputs into a consistent directory layout that
# scripts/analyze_baseline.py knows how to parse.
#
# Works on git bash (Windows + Docker Desktop), macOS, and Linux.
#
# Example — anchor baseline on the user's PC before Phase 1 optimizations:
#   scripts/sitespeed_runner.sh --probe cn-pc --scenario s4 --device both
#
# Cells emit artifacts into:
#   docs/perf-baselines/<YYYY-MM-DD>-<short-sha>/s<N>-<probe>-<device>/
#
# This PR only implements S4 (anonymous Landing). S1-S3 (login-required
# flows) come in a follow-up — they need scripted flows and test creds,
# which deserve their own PR.

set -euo pipefail

IMAGE="sitespeedio/sitespeed.io:latest"
DEFAULT_URL="https://www.praxys.run/"
DEFAULT_RUNS=3

PROBE=""
SCENARIOS="s4"
DEVICES="both"
URL="$DEFAULT_URL"
RUNS="$DEFAULT_RUNS"
OUTDIR=""
SHA=""

usage() {
  cat >&2 <<'EOF'
Usage: sitespeed_runner.sh --probe <name> [options]

Required:
  --probe <name>       Probe label baked into filenames (e.g. cn-pc, hk-aci).

Optional:
  --scenario <ids>     Comma-separated: s1,s2,s3,s4,all. Default: s4.
                       (PR-E: only s4 is implemented.)
  --device <dev>       desktop | mobile | both. Default: both.
  --url <url>          Target URL. Default: https://www.praxys.run/
  --runs <N>           Sitespeed iterations per cell. Default: 3.
  --outdir <path>      Output root. Default: docs/perf-baselines/<date>-<sha>/
  --sha <sha>          Override the sha suffix in the default outdir.
  -h, --help           Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --probe)     PROBE="$2"; shift 2 ;;
    --scenario|--scenarios) SCENARIOS="$2"; shift 2 ;;
    --device|--devices)     DEVICES="$2"; shift 2 ;;
    --url)       URL="$2"; shift 2 ;;
    --runs)      RUNS="$2"; shift 2 ;;
    --outdir)    OUTDIR="$2"; shift 2 ;;
    --sha)       SHA="$2"; shift 2 ;;
    -h|--help)   usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$PROBE" ]]; then
  echo "Error: --probe is required (e.g. --probe cn-pc)" >&2
  usage
  exit 1
fi

if [[ -z "$OUTDIR" ]]; then
  if [[ -z "$SHA" ]]; then
    SHA="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
  fi
  OUTDIR="docs/perf-baselines/$(date +%Y-%m-%d)-${SHA}"
fi
mkdir -p "$OUTDIR"

if [[ "$SCENARIOS" == "all" ]]; then
  SCENARIOS="s1,s2,s3,s4"
fi
IFS=',' read -ra SCENARIO_LIST <<< "$SCENARIOS"

case "$DEVICES" in
  both)    DEVICE_LIST=("desktop" "mobile") ;;
  desktop) DEVICE_LIST=("desktop") ;;
  mobile)  DEVICE_LIST=("mobile") ;;
  *) echo "Error: --device must be desktop|mobile|both" >&2; exit 1 ;;
esac

# Resolve outdir to an absolute path for the Docker bind-mount.
# On git bash, pwd returns /d/... which Docker Desktop for Windows converts
# automatically. On macOS/Linux this is a regular absolute path.
ABS_OUTDIR="$(cd "$OUTDIR" && pwd)"

run_cell() {
  local scenario="$1"
  local device="$2"
  local cell="${scenario}-${PROBE}-${device}"
  local cell_dir="${ABS_OUTDIR}/${cell}"

  case "$scenario" in
    s4) : ;;  # anonymous Landing — supported
    s1|s2|s3)
      echo "  → ${cell}: SKIPPED (login-required scenarios land in a follow-up PR)" >&2
      return 0
      ;;
    *) echo "Error: unknown scenario '$scenario'" >&2; return 1 ;;
  esac

  mkdir -p "$cell_dir"
  echo ">>> ${cell}"
  echo "    url     : $URL"
  echo "    outdir  : $cell_dir"
  echo "    runs    : $RUNS"
  echo "    device  : $device"

  local -a args=(
    --outputFolder "/sitespeed.io/out"
    -n "$RUNS"
    --browsertime.har
    --browsertime.screenshot
  )

  if [[ "$device" == "mobile" ]]; then
    # Chrome DevTools device preset bundles viewport + UA + touch emulation
    # atomically. Sitespeed.io's bare `--mobile` flag isn't consistent
    # across versions; the chrome.mobileEmulation path is stable.
    args+=(
      --browsertime.chrome.mobileEmulation.deviceName "iPhone 14 Pro"
    )
  fi

  # MSYS_NO_PATHCONV prevents git bash from mangling the container-side
  # /sitespeed.io path into a Windows path. --shm-size=1g avoids Chrome's
  # /dev/shm crashes on longer pages (sitespeed.io's documented floor).
  MSYS_NO_PATHCONV=1 docker run --rm --shm-size=1g \
    -v "${cell_dir}:/sitespeed.io/out" \
    "$IMAGE" \
    "${args[@]}" \
    "$URL"
}

echo "Baseline run starting"
echo "  probe     : $PROBE"
echo "  scenarios : ${SCENARIO_LIST[*]}"
echo "  devices   : ${DEVICE_LIST[*]}"
echo "  outdir    : $ABS_OUTDIR"
echo

for scenario in "${SCENARIO_LIST[@]}"; do
  for device in "${DEVICE_LIST[@]}"; do
    run_cell "$scenario" "$device"
  done
done

echo
echo "Done. Next:"
echo "  python scripts/analyze_baseline.py --baseline-dir \"$OUTDIR\""
