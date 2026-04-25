#!/usr/bin/env bash
# Run sitespeed.io for one or more baseline cells (scenario × device) against
# a target URL. Writes outputs into a consistent directory layout that
# scripts/analyze_baseline.py knows how to parse.
#
# Works on git bash (Windows + Docker Desktop), macOS, and Linux.
#
# Example — full Tier 1 from a PC probe:
#   scripts/sitespeed_runner.sh --probe cn-pc --scenario all --device both
#
# Cells emit artifacts into:
#   docs/perf-baselines/<YYYY-MM-DD>-<short-sha>/s<N>-<probe>-<device>/
#
# Scenarios:
#   s4 — Anonymous Landing (no login)
#   s1 — Cold Today via login
#   s2 — Cold Training via login
#   s3 — Warm Today repeat visit (after login + warm-up)
#
# For s1/s2/s3, the runner injects credentials into the container as env
# vars. Defaults to the public demo account (demo@trainsight.dev / demo,
# the same defaults Landing.tsx uses for the "Try the demo" button).
# Override via PRAXYS_PERF_USER + PRAXYS_PERF_PASSWORD if you need a
# different account. PRAXYS_PERF_BASE_URL also overrides the target host.

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
                       s1=Cold Today via login, s2=Cold Training via login,
                       s3=Warm Today repeat visit, s4=Anonymous Landing.
  --device <dev>       desktop | mobile | both. Default: both.
  --url <url>          Target URL for s4. Default: https://www.praxys.run/
                       (Login scenarios use PRAXYS_PERF_BASE_URL — see env.)
  --runs <N>           Sitespeed iterations per cell. Default: 3.
  --outdir <path>      Output root. Default: docs/perf-baselines/<date>-<sha>/
  --sha <sha>          Override the sha suffix in the default outdir.
  -h, --help           Show this help.

Env (login scenarios only):
  PRAXYS_PERF_USER      default: demo@trainsight.dev (public demo account)
  PRAXYS_PERF_PASSWORD  default: demo
  PRAXYS_PERF_BASE_URL  default: https://www.praxys.run (no trailing slash)
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

# Path to the bundled browsertime preScripts that drive S1/S2/S3. Computed
# once and bind-mounted into the container at /sitespeed.io/scripts.
SCRIPTS_DIR_UNIX="$(dirname "$0")/sitespeed_scripts"
if command -v cygpath >/dev/null 2>&1; then
  SCRIPTS_DIR_HOST="$(cygpath -aw "$SCRIPTS_DIR_UNIX")"
else
  SCRIPTS_DIR_HOST="$(cd "$SCRIPTS_DIR_UNIX" && pwd)"
fi

# Public demo defaults — these match the values Landing.tsx ships in its
# "Try the demo" CTA, so they're not secret. Override via PRAXYS_PERF_USER
# / PRAXYS_PERF_PASSWORD if testing against a non-demo account.
: "${PRAXYS_PERF_USER:=demo@trainsight.dev}"
: "${PRAXYS_PERF_PASSWORD:=demo}"
: "${PRAXYS_PERF_BASE_URL:=${URL%/}}"

run_cell() {
  local scenario="$1"
  local device="$2"
  local cell="${scenario}-${PROBE}-${device}"

  case "$scenario" in
    s1|s2|s3|s4) : ;;
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
  echo "    base    : $PRAXYS_PERF_BASE_URL"
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
    # UA is recent iOS Safari. Adequate for render-path measurement.
    args+=(
      --browsertime.viewPort "390x844"
      --browsertime.userAgent "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    )
  fi

  # Build the trailing positional args. S4 = plain URL test. S1/S2/S3 use
  # --multi mode where a JS file drives the browser through the login
  # flow + measured navigation.
  local -a tail_args
  local -a script_mount=()
  if [[ "$scenario" == "s4" ]]; then
    tail_args=("$PRAXYS_PERF_BASE_URL/")
  else
    tail_args=(--multi "/sitespeed.io/scripts/${scenario}.js")
    script_mount=(-v "${SCRIPTS_DIR_HOST}:/sitespeed.io/scripts:ro")
  fi

  # --shm-size=1g avoids Chrome's /dev/shm crashes on larger pages
  # (sitespeed.io's documented floor). MSYS_NO_PATHCONV keeps git bash
  # from converting container-side /sitespeed.io/* paths, while the
  # mount sources are already Windows-style absolute via cygpath -aw so
  # Docker Desktop accepts them as bind-mounts.
  MSYS_NO_PATHCONV=1 docker run --rm --shm-size=1g \
    -v "${cell_mount}:/sitespeed.io/out" \
    "${script_mount[@]}" \
    -e "PRAXYS_PERF_USER=${PRAXYS_PERF_USER}" \
    -e "PRAXYS_PERF_PASSWORD=${PRAXYS_PERF_PASSWORD}" \
    -e "PRAXYS_PERF_BASE_URL=${PRAXYS_PERF_BASE_URL}" \
    "$IMAGE" \
    "${args[@]}" \
    "${tail_args[@]}"
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
