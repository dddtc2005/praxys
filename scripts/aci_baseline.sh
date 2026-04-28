#!/usr/bin/env bash
# Run sitespeed.io inside an Azure Container Instance in a chosen region —
# the cross-region counterpart of scripts/sitespeed_runner.sh (which runs
# Docker locally).
#
# Why this exists: real users hit praxys.run from CN, US-West, and EU.
# Local Docker on a CN PC captures CN reality, but EU/US-West numbers
# need probes physically in those regions. ACI is the cheapest way —
# spin one up on demand, run the baseline, throw it away.
#
# Per-region design (one ACI per probe-device, scenarios serial inside):
# the previous incarnation lived in .github/workflows/perf-baseline.yml as
# a 24-cell GH Actions matrix (4 scenarios × 3 probes × 2 devices), each
# cell its own ACI. ACI cold-start is 3-8 min per cell vs ~5 min of work,
# so half the wall-clock and half the spend was provisioning. This script
# spins one warm container per probe-device pair and runs all four
# scenarios serially against it. Failure isolation coarsens — a container
# crash takes out 4 scenarios — but at this cadence (one full sweep per
# perf checkpoint, manually triggered) re-running a single cell is cheap.
#
# Output layout matches scripts/sitespeed_runner.sh exactly so
# scripts/analyze_baseline.py works on either source:
#   docs/perf-baselines/<YYYY-MM-DD>-<short-sha>/s<N>-<probe>-<device>/
#
# Prereqs (one-time per developer):
#   - `az login` (any account with Contributor on rg-trainsight)
#   - Docker NOT required — ACI runs the sitespeed.io image, not your
#     machine. The shared storage account stperftrainsight already exists
#     in eastasia (see docs/perf-baselines/ci-setup.md → "Reproducing
#     from scratch" if you're forking).
#
# Example — full sweep against the EU probe:
#   scripts/aci_baseline.sh --probe northeurope --device both \
#     --scenario all --reason "post-L3 anchor"
#
# Single cell:
#   scripts/aci_baseline.sh --probe westus --device desktop --scenario s4
#
# Cross-region SMB note (#163): visual-metrics is force-disabled because
# sitespeed.io's frame-by-frame PNG writes choke on cross-region Azure File
# RTT (~250 ms × hundreds of frames + 1000-IOPS share throttle). Speed
# Index is the only metric we lose; it's not surfaced in any
# docs/perf-baselines/*.md. FCP/LCP/TTI/TTFB/CLS still come through
# Chrome's PerformanceObserver and land in the HAR as usual.

set -euo pipefail

# Azure resources — these live in rg-trainsight on the praxys subscription.
# All already provisioned; see docs/perf-baselines/ci-setup.md if you're
# rebuilding from scratch.
AZ_SUBSCRIPTION="${AZ_SUBSCRIPTION:-3ff02750-211c-4579-94a6-8c9af4e6d891}"
AZ_RG="${AZ_RG:-rg-trainsight}"
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-stperftrainsight}"
FILE_SHARE="${FILE_SHARE:-perfbaselines}"
ACI_IMAGE="${ACI_IMAGE:-sitespeedio/sitespeed.io:latest}"

DEFAULT_URL="https://www.praxys.run/"
DEFAULT_RUNS=3

PROBE=""
SCENARIOS="all"
DEVICES="both"
URL="$DEFAULT_URL"
RUNS="$DEFAULT_RUNS"
OUTDIR=""
SHA=""
REASON=""
KEEP_ACI=0

# Git Bash on Windows translates any argument that looks Unix-absolute
# (`/sitespeed.io/out`) into a Windows path (`D:/Program Files/Git/sitespeed.io/out`)
# before exec'ing the child process. Two of the args we pass to
# `az container create` — `--azure-file-volume-mount-path` and
# `--command-line` — are deliberately container-side Linux paths. With
# the conversion they end up containing `:` (the drive-letter colon),
# which trips `az` with "The volume mount path cannot contain ':'".
# `MSYS_NO_PATHCONV=1` opts out of the translation. No-op on macOS /
# Linux. (The local Docker runner sets this per-command for the same
# reason — see `MSYS_NO_PATHCONV=1 docker run …` in sitespeed_runner.sh.)
export MSYS_NO_PATHCONV=1

usage() {
  cat >&2 <<'EOF'
Usage: aci_baseline.sh --probe <region> [options]

Required:
  --probe <region>      Azure region: eastasia | westus | northeurope.
                        (Add new regions by extending VALID_PROBES below.)

Optional:
  --scenario <ids>      Comma-separated: s1,s2,s3,s4,all. Default: all.
                        s1=Cold Today via login, s2=Cold Training via
                        login, s3=Warm Today repeat visit, s4=Anonymous
                        Landing.
  --device <dev>        desktop | mobile | both. Default: both.
                        "both" runs the device pair as two separate ACIs
                        sequentially (different viewports = different
                        warm-up assumptions, cleaner than one container
                        flipping viewports between scenarios).
  --url <url>           Target URL for s4 + base for login scenarios.
                        Default: https://www.praxys.run/
  --runs <N>            Sitespeed iterations per cell. Default: 3.
  --outdir <path>       Output root. Default:
                        docs/perf-baselines/<YYYY-MM-DD>-<short-sha>/
  --sha <sha>           Override the sha suffix in the default outdir.
  --reason <text>       Free-text reason for this baseline (logged only).
  --keep-aci            Don't delete the container at the end (debug).
  -h, --help            Show this help.

Env (login scenarios only):
  PRAXYS_PERF_USER      default: demo@trainsight.dev (public demo account)
  PRAXYS_PERF_PASSWORD  default: demo
  PRAXYS_PERF_BASE_URL  default: <url> with trailing slash stripped

Auth:
  Uses your `az` CLI session. Run `az login` first. The storage account
  key is fetched on demand — no secret needs to live in your env.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --probe)        PROBE="$2"; shift 2 ;;
    --scenario|--scenarios) SCENARIOS="$2"; shift 2 ;;
    --device|--devices)     DEVICES="$2"; shift 2 ;;
    --url)          URL="$2"; shift 2 ;;
    --runs)         RUNS="$2"; shift 2 ;;
    --outdir)       OUTDIR="$2"; shift 2 ;;
    --sha)          SHA="$2"; shift 2 ;;
    --reason)       REASON="$2"; shift 2 ;;
    --keep-aci)     KEEP_ACI=1; shift ;;
    -h|--help)      usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

VALID_PROBES=(eastasia westus northeurope)
if [[ -z "$PROBE" ]]; then
  echo "Error: --probe is required (one of: ${VALID_PROBES[*]})" >&2
  usage
  exit 1
fi
if [[ ! " ${VALID_PROBES[*]} " == *" $PROBE "* ]]; then
  echo "Error: unknown --probe '$PROBE'. Valid: ${VALID_PROBES[*]}" >&2
  echo "       For local-machine probes (cn-pc, hk-laptop, etc.) use scripts/sitespeed_runner.sh." >&2
  exit 1
fi

# Verify az login state up front so we fail fast, not 5 minutes into a
# storage-key call. `az account show` exits non-zero if there is no
# active session; we capture the subscription it would use as a sanity
# check and bail with a clear message.
if ! az account show --subscription "$AZ_SUBSCRIPTION" >/dev/null 2>&1; then
  echo "Error: az CLI is not logged in to subscription $AZ_SUBSCRIPTION." >&2
  echo "       Run: az login" >&2
  echo "       (Then if you have multiple tenants: az account set --subscription $AZ_SUBSCRIPTION)" >&2
  exit 1
fi

if [[ "$SCENARIOS" == "all" ]]; then
  SCENARIOS="s1,s2,s3,s4"
fi
IFS=',' read -ra SCENARIO_LIST <<< "$SCENARIOS"
for s in "${SCENARIO_LIST[@]}"; do
  case "$s" in
    s1|s2|s3|s4) : ;;
    *) echo "Error: unknown scenario '$s' (valid: s1, s2, s3, s4, all)" >&2; exit 1 ;;
  esac
done

case "$DEVICES" in
  both)    DEVICE_LIST=("desktop" "mobile") ;;
  desktop) DEVICE_LIST=("desktop") ;;
  mobile)  DEVICE_LIST=("mobile") ;;
  *) echo "Error: --device must be desktop|mobile|both" >&2; exit 1 ;;
esac

if [[ -z "$SHA" ]]; then
  SHA="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
fi
if [[ -z "$OUTDIR" ]]; then
  OUTDIR="docs/perf-baselines/$(date +%Y-%m-%d)-${SHA}"
fi
mkdir -p "$OUTDIR"

# Fetch the storage key on demand. Any developer with Contributor on
# rg-trainsight can read it — we don't ship it in env / commit it. The
# key is needed twice: once to mount the share into ACI (passed via
# `az container create --azure-file-volume-account-key`) and once to
# upload preScripts + download results from outside the container (via
# `az storage file upload-batch / download-batch`).
echo "Fetching storage key from $STORAGE_ACCOUNT (one-time per run)..."
STORAGE_KEY="$(az storage account keys list \
  --subscription "$AZ_SUBSCRIPTION" \
  --resource-group "$AZ_RG" \
  --account-name "$STORAGE_ACCOUNT" \
  --query "[0].value" -o tsv)"
if [[ -z "$STORAGE_KEY" ]]; then
  echo "Error: could not fetch storage key for $STORAGE_ACCOUNT (need read access on $AZ_RG)." >&2
  exit 1
fi

# Per-run namespace keeps two concurrent runs from clobbering each other
# on the shared file share. PID is enough — runs are minutes apart in
# practice and the share gets cleaned up at the end either way.
RUN_ID="$(date +%Y%m%d-%H%M%S)-$$"

# Login defaults match scripts/sitespeed_runner.sh — the public demo
# account that Landing.tsx ships in its "Try the demo" CTA. Override via
# env if testing against a non-demo account.
: "${PRAXYS_PERF_USER:=demo@trainsight.dev}"
: "${PRAXYS_PERF_PASSWORD:=demo}"
: "${PRAXYS_PERF_BASE_URL:=${URL%/}}"

SCRIPTS_LOCAL_DIR="$(dirname "$0")/sitespeed_scripts"
SHARE_SCRIPTS_PATH="scripts-${RUN_ID}"
SHARE_OUT_PATH="out-${RUN_ID}"

# The wrapper that runs inside the container. We generate it on the fly
# rather than committing a sibling .sh file because the only reader is
# the ACI we control, and inlining keeps the orchestration logic in one
# file. Keep this dead-simple — it runs inside the official sitespeed.io
# image where /start.sh prepares Chrome and execs sitespeed.io.
WRAPPER_TMP="$(mktemp -t aci-baseline-run.XXXXXX.sh)"

# `mktemp` returns the MSYS-style path (`/tmp/...`) on Git Bash. With
# MSYS_NO_PATHCONV=1 set above, Git Bash now leaves that path literal
# when we exec child processes — but `az` is a Python program that
# doesn't share MSYS's /tmp mount fiction, so it tries to open
# `D:\tmp\…` and 404s. cygpath -aw turns the path into a Windows-style
# absolute (`C:\Users\…\Temp\aci-baseline-run.…`) that `az` resolves
# correctly. Local upload paths that go to `az` in this script (the
# preScripts dir, the wrapper) need this conversion; everything else
# is either a share path (no leading slash, MSYS-untouched) or an
# explicit container-side path that we *want* literal.
to_host_path() {
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -aw "$1"
  else
    echo "$1"
  fi
}
WRAPPER_TMP_HOST="$(to_host_path "$WRAPPER_TMP")"
SCRIPTS_LOCAL_DIR_HOST="$(to_host_path "$SCRIPTS_LOCAL_DIR")"
OUTDIR_HOST="$(to_host_path "$OUTDIR")"

# Containers we've asked Azure to create. Populated *before* the create
# call so that even if creation 5xxs partway through, the trap still
# attempts deletion (a delete against a nonexistent name is idempotent).
# Drained on Ctrl-C / EXIT — see `finalize` below. Without this, a Ctrl-C
# during the 25/45-min polling loop leaks an ACI in a foreign region
# with the storage key still mounted, billing $0.05–0.30 silently until
# the user remembers to `az container list --rg rg-trainsight`.
CONTAINERS_TO_DELETE=()

# Install the EXIT trap *immediately* after WRAPPER_TMP exists. Even
# though `finalize` is defined further down, bash trap actions are
# resolved at signal-fire time, not at `trap` time — so the forward
# reference is fine. Setting the trap up here (rather than after the
# function definitions ~250 lines below) closes the window where a
# heredoc-cat failure or upload_inputs error would orphan the tempfile.
# Bash overwrites EXIT traps on subsequent `trap … EXIT` calls, so we
# only get one — `finalize` does both tempfile + share + container
# cleanup combined.
trap finalize EXIT

cat >"$WRAPPER_TMP" <<'WRAPPER_EOF'
#!/bin/sh
# In-container wrapper. Reads everything from env vars; keeps ACI's
# whitespace-shredding argv parser out of the picture (passing the
# scenario list via env survives, passing it via --command-line does
# not — see the comment block in the GHA workflow we replaced).
set -u
echo "[wrapper] RUN_ID=$RUN_ID PROBE=$PROBE DEVICE=$DEVICE SCENARIOS=$SCENARIOS"
echo "[wrapper] BASE_URL=$BASE_URL RUNS=$RUNS"

OUT_ROOT="/sitespeed.io/out/$SHARE_OUT_PATH"
SCRIPTS_DIR="/sitespeed.io/out/$SHARE_SCRIPTS_PATH"
mkdir -p "$OUT_ROOT"

if [ "$DEVICE" = "mobile" ]; then
  # Viewport-only — see the GHA workflow comment we replaced for why we
  # don't pass --browsertime.userAgent through ACI argv. Inside the
  # wrapper, sitespeed.io's own argv parser handles quoted UA strings
  # fine, but keeping parity with the original CI cell makes
  # CI-anchored numbers comparable to local-runner numbers.
  DEVICE_ARGS="--browsertime.viewPort 390x844"
else
  DEVICE_ARGS=""
fi

# --browsertime.visualMetrics=false closes #163 (cross-region SMB chokes
# on per-frame PNG writes). The metric we lose, Speed Index, is not
# surfaced in any docs/perf-baselines/*.md — every cited number is FCP /
# LCP / TTI / TTFB / CLS or an API p50/p95, all of which come through
# Chrome's PerformanceObserver, not visualmetrics.
#
# CAVEAT: every value in BASE_ARGS / DEVICE_ARGS must be space-free. We
# rely on unquoted expansion below (`$BASE_ARGS $DEVICE_ARGS`) to split
# them into argv tokens — same semantics as the ACI argv parser, which
# is exactly the reason the orchestrator (host script) had to pass
# values like the mobile UA via env vars. If you need a value with
# spaces in it, branch into a per-device call with an explicit
# argv array, don't try to embed it here.
BASE_ARGS="-n $RUNS --browsertime.visualMetrics=false"

run_one() {
  s="$1"
  cell_dir="$OUT_ROOT/${s}-${PROBE}-${DEVICE}"
  echo "[wrapper] === Running $s into $cell_dir ==="
  mkdir -p "$cell_dir"
  if [ "$s" = "s4" ]; then
    /start.sh "$BASE_URL/" $BASE_ARGS $DEVICE_ARGS --outputFolder "$cell_dir" \
      || echo "[wrapper] !!! $s failed (exit $?) — continuing"
  else
    /start.sh --multi "$SCRIPTS_DIR/${s}.js" $BASE_ARGS $DEVICE_ARGS --outputFolder "$cell_dir" \
      || echo "[wrapper] !!! $s failed (exit $?) — continuing"
  fi
}

for s in $SCENARIOS; do
  run_one "$s"
done

echo "[wrapper] === All scenarios done ==="
WRAPPER_EOF

cleanup_share_paths() {
  # Always remove our run's namespaces from the share — the local
  # download is the durable copy, and leaving the share dirty trips up
  # the next concurrent run if we ever loosen the unique RUN_ID.
  for path in "$SHARE_SCRIPTS_PATH" "$SHARE_OUT_PATH"; do
    az storage file delete-batch \
      --subscription "$AZ_SUBSCRIPTION" \
      --account-name "$STORAGE_ACCOUNT" \
      --account-key "$STORAGE_KEY" \
      --source "$FILE_SHARE" \
      --pattern "${path}/*" \
      --output none 2>/dev/null || true
  done
}

upload_inputs() {
  # PreScripts + wrapper into a per-run scripts-<runid>/ folder on the
  # share. ACI mounts the share at /sitespeed.io/out, so the container
  # sees them at /sitespeed.io/out/scripts-<runid>/.
  echo "Uploading preScripts + wrapper to share://${SHARE_SCRIPTS_PATH}/"
  az storage file upload-batch \
    --subscription "$AZ_SUBSCRIPTION" \
    --account-name "$STORAGE_ACCOUNT" \
    --account-key "$STORAGE_KEY" \
    --destination "$FILE_SHARE" \
    --destination-path "$SHARE_SCRIPTS_PATH" \
    --source "$SCRIPTS_LOCAL_DIR_HOST" \
    --output none
  az storage file upload \
    --subscription "$AZ_SUBSCRIPTION" \
    --account-name "$STORAGE_ACCOUNT" \
    --account-key "$STORAGE_KEY" \
    --share-name "$FILE_SHARE" \
    --path "$SHARE_SCRIPTS_PATH/run.sh" \
    --source "$WRAPPER_TMP_HOST" \
    --output none
}

run_one_device() {
  local device="$1"
  local container_name="sitespeed-${PROBE}-${device}-${RUN_ID}"
  local scenarios_space_separated="${SCENARIO_LIST[*]}"

  echo
  echo "================================================================"
  echo " Probe:    $PROBE"
  echo " Device:   $device"
  echo " Scenarios: $scenarios_space_separated"
  echo " Container: $container_name"
  echo " Reason:   ${REASON:-<unspecified>}"
  echo "================================================================"

  echo "Provisioning ACI in $PROBE..."
  # Track the container before issuing the create so a Ctrl-C between
  # this line and `az container delete` (success-path on line ~437) is
  # still cleaned up by the EXIT trap.
  CONTAINERS_TO_DELETE+=("$container_name")
  az container create \
    --subscription "$AZ_SUBSCRIPTION" \
    --resource-group "$AZ_RG" \
    --name "$container_name" \
    --image "$ACI_IMAGE" \
    --os-type Linux \
    --location "$PROBE" \
    --cpu 2 --memory 4 \
    --restart-policy Never \
    --azure-file-volume-account-name "$STORAGE_ACCOUNT" \
    --azure-file-volume-account-key "$STORAGE_KEY" \
    --azure-file-volume-share-name "$FILE_SHARE" \
    --azure-file-volume-mount-path /sitespeed.io/out \
    --environment-variables \
      "RUN_ID=$RUN_ID" \
      "PROBE=$PROBE" \
      "DEVICE=$device" \
      "SCENARIOS=$scenarios_space_separated" \
      "BASE_URL=$PRAXYS_PERF_BASE_URL" \
      "RUNS=$RUNS" \
      "SHARE_OUT_PATH=$SHARE_OUT_PATH" \
      "SHARE_SCRIPTS_PATH=$SHARE_SCRIPTS_PATH" \
      "PRAXYS_PERF_USER=$PRAXYS_PERF_USER" \
      "PRAXYS_PERF_PASSWORD=$PRAXYS_PERF_PASSWORD" \
      "PRAXYS_PERF_BASE_URL=$PRAXYS_PERF_BASE_URL" \
    --command-line "sh /sitespeed.io/out/$SHARE_SCRIPTS_PATH/run.sh" \
    --no-wait \
    --output none

  # Region-aware deadline (#151): cross-region cold-start runs ~8 min
  # before sitespeed even starts, plus ~5 min × 4 scenarios serial = ~28
  # min worst case. eastasia provisions in ~3 min so 25 min is plenty.
  case "$PROBE" in
    eastasia) DEADLINE_SEC=1500 ;;        # 25 min
    *)        DEADLINE_SEC=2700 ;;        # 45 min — cross-region
  esac
  local deadline_min=$((DEADLINE_SEC / 60))
  local deadline=$(($(date +%s) + DEADLINE_SEC))
  echo "Polling for exit (deadline ${deadline_min} min)..."
  local exit_code=""
  while [ "$(date +%s)" -lt "$deadline" ]; do
    # Exit code presence is the canonical "done" marker — currentState.state
    # can read "Running" after the process actually exited (we hung 15 of
    # 15 cross-region runs on that bug before switching to exit_code).
    exit_code="$(az container show \
      --subscription "$AZ_SUBSCRIPTION" \
      --resource-group "$AZ_RG" \
      --name "$container_name" \
      --query "containers[0].instanceView.currentState.exitCode" -o tsv 2>/dev/null || true)"
    if [ -n "$exit_code" ] && [ "$exit_code" != "null" ]; then
      break
    fi
    local state
    state="$(az container show \
      --subscription "$AZ_SUBSCRIPTION" \
      --resource-group "$AZ_RG" \
      --name "$container_name" \
      --query "containers[0].instanceView.currentState.state" -o tsv 2>/dev/null || true)"
    echo "  [$(date -u +%T)] state=${state:-pending} exit=${exit_code:-pending}"
    sleep 20
  done

  echo
  echo "---- container logs (tail) ----"
  az container logs \
    --subscription "$AZ_SUBSCRIPTION" \
    --resource-group "$AZ_RG" \
    --name "$container_name" 2>&1 | tail -80 || true
  echo "-------------------------------"

  if [ -z "$exit_code" ] || [ "$exit_code" = "null" ]; then
    echo "WARN: polling timed out at ${deadline_min} min — will still try to download whatever made it to the share." >&2
    exit_code="timeout"
  fi

  echo "Downloading results from share://${SHARE_OUT_PATH}/ → $OUTDIR/"
  # `set +e` for the download because we want to keep going even if a
  # cell produced no output — the next step warns about it.
  set +e
  az storage file download-batch \
    --subscription "$AZ_SUBSCRIPTION" \
    --account-name "$STORAGE_ACCOUNT" \
    --account-key "$STORAGE_KEY" \
    --source "$FILE_SHARE" \
    --pattern "${SHARE_OUT_PATH}/*" \
    --destination "$OUTDIR_HOST" \
    --output none
  set -e

  # Move out-<runid>/s<N>-<probe>-<device>/ → s<N>-<probe>-<device>/
  # so analyze_baseline.py's per-cell expectation lines up. Loop is
  # idempotent — extra `mv` calls between cells of the same RUN_ID are
  # harmless because each cell's dir name is unique.
  if [ -d "$OUTDIR/$SHARE_OUT_PATH" ]; then
    for cell in "$OUTDIR/$SHARE_OUT_PATH"/s*-*; do
      [ -d "$cell" ] || continue
      mv "$cell" "$OUTDIR/" 2>/dev/null || echo "WARN: could not move $cell (already exists?)" >&2
    done
    rmdir "$OUTDIR/$SHARE_OUT_PATH" 2>/dev/null || true
  fi

  # Match the .gitignore policy for docs/perf-baselines/: drop video /
  # filmstrip / screenshots so we never accidentally commit hundreds of
  # MB of binaries. HARs + browsertime.json + pages.json stay.
  find "$OUTDIR" -type d \( -name video -o -name filmstrip -o -name screenshots \) \
    -exec rm -rf {} + 2>/dev/null || true

  if [ "$KEEP_ACI" = "1" ]; then
    echo "Keeping ACI alive (--keep-aci): $container_name"
  else
    echo "Deleting ACI $container_name..."
    az container delete \
      --subscription "$AZ_SUBSCRIPTION" \
      --resource-group "$AZ_RG" \
      --name "$container_name" \
      --yes --output none || true
    # Already deleted on the success path; remove from the trap's
    # to-delete list so we don't issue a redundant delete (slow & adds
    # noise to logs). Iterates because bash arrays don't have an
    # element-remove primitive.
    local i remaining=()
    for i in "${CONTAINERS_TO_DELETE[@]}"; do
      [ "$i" = "$container_name" ] || remaining+=("$i")
    done
    CONTAINERS_TO_DELETE=("${remaining[@]}")
  fi

  if [ "$exit_code" = "0" ]; then
    echo "✓ ${PROBE}-${device} done (exit 0)"
  elif [ "$exit_code" = "timeout" ]; then
    echo "✗ ${PROBE}-${device} polling timed out — partial results in $OUTDIR" >&2
  else
    echo "✗ ${PROBE}-${device} container exit code: $exit_code — partial results in $OUTDIR" >&2
  fi
}

# Trap-installed at the top of the script (right after WRAPPER_TMP=…).
# Runs on every exit path: clean termination, `set -e` failure, Ctrl-C.
# Three jobs:
#   1. Delete the local heredoc tempfile.
#   2. Delete any ACIs still in CONTAINERS_TO_DELETE (run_one_device
#      removes successfully-deleted entries from the list, so the only
#      survivors are containers that were created but not yet
#      explicitly torn down — typically a Ctrl-C mid-poll). Skipped if
#      --keep-aci is set, so a debug session can `az container exec`
#      into the kept container.
#   3. Wipe our run-id-namespaced paths off the share. Skipped when
#      --keep-aci so the still-running container can read its mount.
# `set +e` because we're best-effort cleanup — a transient az failure
# shouldn't bubble out and make the EXIT-trap exit code lie about the
# real exit cause.
finalize() {
  set +e
  rm -f "$WRAPPER_TMP" 2>/dev/null

  if [ "$KEEP_ACI" = "1" ]; then
    if [ ${#CONTAINERS_TO_DELETE[@]} -gt 0 ]; then
      echo "[--keep-aci] Leaving ${#CONTAINERS_TO_DELETE[@]} container(s) running:" >&2
      printf '  %s\n' "${CONTAINERS_TO_DELETE[@]}" >&2
      echo "[--keep-aci] Manual cleanup: az container delete -g $AZ_RG -n <name> --yes" >&2
      echo "[--keep-aci] Leaving share namespaces in place so the container can still see its mount." >&2
    fi
    return
  fi

  if [ ${#CONTAINERS_TO_DELETE[@]} -gt 0 ]; then
    echo "[finalize] Tearing down ${#CONTAINERS_TO_DELETE[@]} ACI(s) (Ctrl-C / failure path)..." >&2
    for c in "${CONTAINERS_TO_DELETE[@]}"; do
      echo "  deleting $c" >&2
      az container delete \
        --subscription "$AZ_SUBSCRIPTION" \
        --resource-group "$AZ_RG" \
        --name "$c" \
        --yes --output none 2>/dev/null || \
          echo "  WARN: failed to delete $c — clean up manually with az container delete" >&2
    done
  fi

  cleanup_share_paths
}

archive_to_blob() {
  # Bundle every cell this run produced into one tarball and push to the
  # `perfbaselines-archive` blob container on stperftrainsight. Why blob,
  # not the existing perfbaselines File share: File is for active
  # staging (5 GB quota, ~3× the per-GB cost of blob); blob is the right
  # primitive for an immutable, named, per-run snapshot. Already
  # documented as the archive tier in docs/perf-baselines/ci-setup.md
  # under "HAR storage policy".
  local container="perfbaselines-archive"
  local archive_blob="aci-$(date +%Y%m%d-%H%M%S)-${PROBE}-${SHA}.tar.gz"
  local archive_local
  archive_local="$(mktemp -t "aci-baseline-archive.XXXXXX.tar.gz")"
  local archive_local_host
  archive_local_host="$(to_host_path "$archive_local")"

  # Only tar cells from THIS run's probe. OUTDIR is shared per-day-per-sha
  # and may already contain cells from earlier --probe invocations; we
  # don't want to re-archive those on every run. Pattern matches the
  # cell-naming convention enforced in run_one_device:
  # `s<N>-${PROBE}-{desktop|mobile}`.
  local -a cells=()
  local d
  for d in "$OUTDIR"/s*-"${PROBE}"-*; do
    [ -d "$d" ] || continue
    cells+=("$(basename "$d")")
  done
  if [ ${#cells[@]} -eq 0 ]; then
    echo "WARN: no cells matched s*-${PROBE}-* in $OUTDIR — skipping blob archive" >&2
    rm -f "$archive_local"
    return
  fi

  echo
  echo "Archiving ${#cells[@]} cell(s) to blob://${container}/${archive_blob}..."
  if ! tar -czf "$archive_local" -C "$OUTDIR" "${cells[@]}" 2>/dev/null; then
    echo "WARN: tar failed — skipping blob upload (local copy is in $OUTDIR)" >&2
    rm -f "$archive_local"
    return
  fi

  # `--overwrite false` ensures a clock collision (two runs in the same
  # second on the same probe with the same sha) doesn't silently
  # overwrite an earlier archive. The mktemp + RUN_ID + timestamp combo
  # makes that essentially impossible, but the safety belt is free.
  if az storage blob upload \
      --subscription "$AZ_SUBSCRIPTION" \
      --account-name "$STORAGE_ACCOUNT" \
      --account-key "$STORAGE_KEY" \
      --container-name "$container" \
      --name "$archive_blob" \
      --file "$archive_local_host" \
      --overwrite false \
      --output none 2>&1 | tail -5; then
    echo "✓ Archived to https://${STORAGE_ACCOUNT}.blob.core.windows.net/${container}/${archive_blob}"
    echo "  Retrieve later: az storage blob download -c ${container} -n ${archive_blob} -f ./<local>.tar.gz"
  else
    echo "WARN: blob upload failed — local copy is in $OUTDIR" >&2
  fi
  rm -f "$archive_local"
  # Explicit success: rm -f returns 0 even on missing file, but be
  # defensive — set -e at the call site shouldn't be tripped by this
  # function's tail.
  return 0
}

upload_inputs
for device in "${DEVICE_LIST[@]}"; do
  run_one_device "$device"
done

# A failure inside archive_to_blob (transient az glitch, upload conflict,
# locale weirdness on Git Bash, etc.) must not blow away a 30-min sweep
# of just-downloaded HARs. set -e at this scope would treat a non-zero
# return from the function — or any unexpected stderr line bash mistakes
# for a command — as fatal. Demote to a warning; OUTDIR is still on disk
# and the user can re-archive manually:
#   tar -czf /tmp/manual.tar.gz -C $OUTDIR s*-${PROBE}-* &&
#   az storage blob upload --account-name stperftrainsight \
#       --container-name perfbaselines-archive --name <name>.tar.gz \
#       --file /tmp/manual.tar.gz --overwrite false
archive_to_blob || echo "WARN: archive_to_blob exited non-zero (rc=$?) — local copy in $OUTDIR is intact" >&2

echo
echo "Outputs landed in: $OUTDIR"
echo "Next: python scripts/analyze_baseline.py --baseline-dir \"$OUTDIR\""
