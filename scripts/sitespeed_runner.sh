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

# Resolve outdir to an *absolute* path for the Docker bind-mount. On git
# bash we want the Windows-style absolute form (D:\Dev\...) — Docker Desktop
# rejects relative paths (they get parsed as volume names, with restricted
# character set) and doesn't reliably understand the MSYS /d/Dev/... form.
# `cygpath -aw` ships with Git for Windows and does both steps. On
# Linux/macOS we fall back to pwd, which is already absolute.
if command -v cygpath >/dev/null 2>&1; then
  ABS_OUTDIR="$(cygpath -aw "$OUTDIR")"
else
  ABS_OUTDIR="$(cd "$OUTDIR" && pwd)"
fi

run_cell() {
  local scenario="$1"
  local device="$2"
  local cell="${scenario}-${PROBE}-${device}"

  case "$scenario" in
    s4) : ;;  # anonymous Landing — supported
    s1|s2|s3)
      echo "  → ${cell}: SKIPPED (login-required scenarios land in a follow-up PR)" >&2
      return 0
      ;;
    *) echo "Error: unknown scenario '$scenario'" >&2; return 1 ;;
  esac

  # Create the cell dir using the Unix-style path (works in the current
  # shell), then compute an *absolute* Windows-style path for the Docker
  # bind mount (see outer comment on cygpath -aw).
  local cell_unix="${OUTDIR}/${cell}"
  mkdir -p "$cell_unix"
  local cell_mount
  if command -v cygpath >/dev/null 2>&1; then
    cell_mount="$(cygpath -aw "$cell_unix")"
  else
    cell_mount="$(cd "$cell_unix" && pwd)"
  fi

  echo ">>> ${cell}"
  echo "    url     : $URL"
  echo "    outdir  : $cell_mount"
  echo "    runs    : $RUNS"
  echo "    device  : $device"

  # HAR + screenshot + browsertime.json are sitespeed.io defaults, so we
  # don't list them explicitly — the previous code's `--browsertime.har`
  # bare-flag was consumed as a value-taking option in some CLI parsers
  # and silently swallowed the next argument.
  local -a args=(
    --outputFolder "/sitespeed.io/out"
    -n "$RUNS"
  )

  if [[ "$device" == "mobile" ]]; then
    # Explicit viewport + UA is more portable than Chrome's device-name
    # presets — the preset list drifts per Chrome version (146.x doesn't
    # recognize "iPhone 14 Pro" as of this writing, for example), which
    # breaks CI runs silently. Viewport matches iPhone 14 Pro (CSS px),
    # UA is recent iOS Safari. For S4 Landing this is enough — we're
    # measuring render-path, not touch interactions.
    args+=(
      --browsertime.viewPort "390x844"
      --browsertime.userAgent "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    )
  fi

  # --shm-size=1g avoids Chrome's /dev/shm crashes on larger pages
  # (sitespeed.io's documented floor). MSYS_NO_PATHCONV keeps git bash
  # from converting the container-side /sitespeed.io/out argument, while
  # cell_mount is already a Windows-style path so Docker Desktop accepts
  # it as a bind-mount to the real filesystem.
  MSYS_NO_PATHCONV=1 docker run --rm --shm-size=1g \
    -v "${cell_mount}:/sitespeed.io/out" \
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
