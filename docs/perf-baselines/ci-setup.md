# Cross-region perf baselines (`scripts/aci_baseline.sh`)

> Filename is legacy. This used to describe a GitHub Actions workflow
> (`.github/workflows/perf-baseline.yml`) that ran the matrix on every
> dispatch. The workflow burned ~360 GHA-minutes per sweep with no
> additional value over running locally — see issue #161 for the cost
> analysis. It was retired in favour of the on-demand local CLI
> documented below; everything else here (Azure resources, RBAC, archive
> blob) carries over.

This doc covers the cross-region half of the perf-baseline tooling. The
in-region (CN) half lives in [`../../scripts/pc-setup.md`](../../scripts/pc-setup.md)
+ [`../../scripts/sitespeed_runner.sh`](../../scripts/sitespeed_runner.sh).

## What it does

A developer runs `scripts/aci_baseline.sh --probe <region> ...` from
their PC; the script:

1. Validates the chosen probe is one of `eastasia` / `westus` /
   `northeurope` (Azure regions where ACI is available and roughly
   matches our audience macro-regions).
2. Fetches the storage key for `stperftrainsight` via the developer's
   own `az login` session — no secret in the env.
3. Uploads the bundled JS preScripts (`scripts/sitespeed_scripts/*.js`)
   and a generated wrapper (`run.sh`) to a per-run namespace on the
   `perfbaselines` Azure File share.
4. For each requested device (desktop / mobile / both): provisions one
   ACI in `<region>` running `sitespeedio/sitespeed.io:latest` with the
   share mounted at `/sitespeed.io/out`. The wrapper runs all requested
   scenarios serially in that one warm container — provisioning is
   amortized across the full scenario set, not paid 4× over (#161's
   redesign).
5. Polls `containers[0].instanceView.currentState.exitCode` (NOT
   `state == "Terminated"` — that field is unreliable cross-region;
   `exitCode` is set exactly when the process exits). Region-aware
   deadline: 25 min for eastasia, 45 min for cross-region.
6. Downloads the cell directories back into
   `docs/perf-baselines/<YYYY-MM-DD>-<short-sha>/` matching the layout
   `scripts/sitespeed_runner.sh` produces, so
   `scripts/analyze_baseline.py` works on either source.
7. Strips video / filmstrip / screenshots (matches the gitignore policy
   in [`../../.gitignore`](../../.gitignore)) and tears down the ACI +
   share namespace.

Per-cell flow visualization:

```
PC (your laptop)
  └─ az login (existing session, any account with Contributor on rg-trainsight)
       │
       │   az storage file upload-batch  (preScripts + run.sh)
       ▼
  Azure File share `perfbaselines` ─── eastasia
       ▲
       │  mounted at /sitespeed.io/out
       │
  Azure Container Instance (sitespeedio/sitespeed.io:latest, region = --probe)
       └─ run.sh loops:  s4 → s1 → s2 → s3
            └─ each writes browsertime.har + report into share
       ▼
PC: az storage file download-batch ─→ docs/perf-baselines/<date>-<sha>/
```

Output cell layout (one folder per scenario × probe × device):

```
docs/perf-baselines/2026-04-28-<sha>/
├── s1-northeurope-desktop/
│   ├── data/browsertime.har
│   ├── pages/...
│   └── ...
├── s2-northeurope-desktop/
├── s3-northeurope-desktop/
├── s4-northeurope-desktop/
├── s1-northeurope-mobile/
├── ...
```

## Prereqs

One-time per developer:

1. **`az login`** with an account that has Contributor on `rg-trainsight`
   in subscription `3ff02750-211c-4579-94a6-8c9af4e6d891` (the praxys
   subscription). If you have multiple tenants:
   ```bash
   az account set --subscription 3ff02750-211c-4579-94a6-8c9af4e6d891
   ```
   The script verifies this on launch and exits with a clear error if
   not logged in.

2. The `az` CLI extension `containerapp` is **not** required —
   `az container` (Container Instances, not Container Apps) ships with
   the base az CLI.

3. **No** GitHub secret rotation, **no** OIDC service principal, **no**
   per-developer storage key in env. The key is fetched on demand via
   `az storage account keys list` once per run.

## Triggering a baseline

Single cell — quick check on one probe:

```bash
scripts/aci_baseline.sh --probe northeurope --device desktop --scenario s4 \
  --reason "anchor before code-splitting"
```

Full sweep on one probe (all four scenarios × both devices = 8 cells in
2 ACIs):

```bash
scripts/aci_baseline.sh --probe westus --device both --scenario all \
  --reason "after L3 measurement"
```

Cross-three-probes loop, sequentially (the parallelism that mattered in
the old GHA matrix doesn't matter here — wall-clock is happy to stretch
when there's no per-minute spend):

```bash
for probe in eastasia westus northeurope; do
  scripts/aci_baseline.sh --probe "$probe" --device both --scenario all \
    --reason "L4 anchor"
done
python scripts/analyze_baseline.py --baseline-dir docs/perf-baselines/<YYYY-MM-DD>-<sha>
```

## Azure resources

All in `rg-trainsight`, subscription `3ff02750-211c-4579-94a6-8c9af4e6d891`.
Already provisioned on the dddtc2005/praxys account.

| Resource | Name | Purpose |
|---|---|---|
| Storage account | `stperftrainsight` (StorageV2, Standard_LRS, eastasia) | Hosts share + archive |
| File share | `perfbaselines` (5 GB quota) | preScripts upload + sitespeed.io output staging |
| Blob container | `perfbaselines-archive` | Long-term HAR archive (see "HAR storage policy" below) |

Cost: ~$0.05/month for the share at idle + ~$0.05–0.30 per ACI run (a
full 8-cell sweep is roughly $0.30 of compute, billed per-second).

## RBAC

The developer's `az login` account needs:
- **Contributor** on `rg-trainsight` (Azure RBAC) — sufficient for both
  `Microsoft.ContainerInstance/containerGroups/*` and
  `Microsoft.Storage/storageAccounts/listKeys/action`.

That's it. No service principal to manage, no OIDC federation, no GitHub
secret, no `STORAGE_ACCOUNT_KEY` needed in env.

## Reproducing from scratch

If you fork the repo or rebuild the environment in a fresh subscription:

```bash
# 1. Create the storage account + share
az storage account create \
  --subscription <sub> --resource-group <rg> \
  --name <account> --location eastasia \
  --sku Standard_LRS --kind StorageV2

az storage share-rm create \
  --subscription <sub> --resource-group <rg> \
  --storage-account <account> --name perfbaselines --quota 5

# 2. (Optional) Long-term archive container — see HAR storage policy below
az storage container create \
  --account-name <account> \
  --name perfbaselines-archive \
  --auth-mode login

# 3. Update the env defaults at the top of scripts/aci_baseline.sh
#    (AZ_SUBSCRIPTION, AZ_RG, STORAGE_ACCOUNT, FILE_SHARE) or pass them
#    via env on each run.
```

## HAR storage policy

Since the repo went public on 2026-04-26, raw HAR files are kept **out
of the repo**. They contain HTTP request/response metadata including
authorization headers (which had stale JWT bearer tokens before the JWT
rotation that accompanied the public flip). HARs now live in two places:

1. **Local working copy.** Each `aci_baseline.sh` run downloads HARs to
   `docs/perf-baselines/<date>-<sha>/` on your PC. The repo's
   [`.gitignore`](../../.gitignore) excludes `*.har` so they don't enter
   git accidentally. Sufficient for "I want to re-analyze the most
   recent sweep on my own machine."
2. **Azure blob container `perfbaselines-archive`** on storage account
   `stperftrainsight` in `rg-trainsight`. Private, durable, requires
   az auth. Holds anything older than 30 days that's worth keeping.
   The pre-public bundle of all HARs that used to be committed is at
   `perfbaselines-HARs-pre-public-2026-04-26.tar.gz`.

There is no longer a "GitHub Actions artifact" tier — the workflow that
produced those was retired. If you need to share a HAR with another
developer, upload it to the archive container by hand:

```bash
KEY=$(az storage account keys list -g rg-trainsight -n stperftrainsight \
  --query "[0].value" -o tsv)
az storage blob upload \
  --account-name stperftrainsight --account-key "$KEY" \
  --container-name perfbaselines-archive \
  --name "<descriptive-name>.tar.gz" \
  --file ./local-bundle.tar.gz
```

To retrieve the pre-public archive (e.g. to re-analyze an old baseline
against a current code change):

```bash
KEY=$(az storage account keys list -g rg-trainsight -n stperftrainsight \
  --query "[0].value" -o tsv)
az storage blob download \
  --account-name stperftrainsight \
  --account-key "$KEY" \
  --container-name perfbaselines-archive \
  --name perfbaselines-HARs-pre-public-2026-04-26.tar.gz \
  --file ./pre-public-hars.tar.gz
tar xzf ./pre-public-hars.tar.gz   # extracts into docs/perf-baselines/<date>/...
python scripts/analyze_baseline.py --baseline-dir docs/perf-baselines/<date>-<sha>
```

The `.gitignore` rule `docs/perf-baselines/**/*.har` ensures these
extracted HARs don't accidentally re-enter the repo on the next commit.

## Login-scripted scenarios (S1/S2/S3)

When `--scenario` includes `s1`, `s2`, or `s3`, the script uploads
`scripts/sitespeed_scripts/*.js` to a per-run scripts folder on the
`perfbaselines` share. The container mounts the share at
`/sitespeed.io/out`, so the preScripts appear at
`/sitespeed.io/out/scripts-<runid>/<scenario>.js`. Sitespeed.io is then
invoked with `--multi /sitespeed.io/out/scripts-<runid>/<scenario>.js`
instead of a target URL.

The preScripts read three env vars (passed via `az container create
--environment-variables`):

- `PRAXYS_PERF_BASE_URL` — derived from `--url` (trailing slash
  stripped, e.g. `https://www.praxys.run`).
- `PRAXYS_PERF_USER` — defaults to `demo@trainsight.dev` (public demo
  account, same one Landing's "Try the demo" CTA ships). Override via
  shell env.
- `PRAXYS_PERF_PASSWORD` — defaults to `demo`. Override via shell env.

The defaults match `scripts/sitespeed_runner.sh` so a cloud cell and a
local cell of the same scenario measure the same flow against the same
account.

## Visual metrics are off cross-region (issue #163)

The wrapper runs sitespeed.io with `--browsertime.visualMetrics=false`.
Storage `stperftrainsight` lives in eastasia; cross-region ACIs mount
the share over Azure File / SMB at ~250 ms RTT per op. Sitespeed's
visual-metrics step writes ~200 per-frame PNGs per iteration, each
needing 3+ RTTs ≈ 750 ms cross-region. Three iterations × this is
5–10 minutes of pure storage I/O, and Standard-tier shares throttle at
1000 IOPS so a burst of frame writes can stall completely. Within-region
(eastasia → eastasia, ~2 ms RTT) the same workflow finishes in 6–13 min
and visual-metrics is invisible — but our own docs/perf-baselines/* never
cite Speed Index (every number is FCP / LCP / TTI / TTFB / CLS or an API
p50/p95) so the loss is invisible to every consumer of the checkpoint.

If you ever do need Speed Index for a specific investigation, drop
`--browsertime.visualMetrics=false` from the wrapper and only run the
`eastasia` probe (the only place the SMB latency doesn't kill it).

## Known limitations

- **No mainland-China POPs.** Azure has none in the public cloud;
  closest is `eastasia` (Hong Kong). For CN-from-inside-the-GFW numbers
  keep using `scripts/sitespeed_runner.sh` on an operator PC.
- **Per-region container failure isolation.** A container crash on cell
  N takes out cells N+1..4 in the same probe-device. Re-run that
  device-pair (a single ACI of ~8 minutes) to recover; the JSON layout
  is the same so the analyzer doesn't care that two cells came from two
  different runs.
- **One ACI per probe-device, not per scenario.** This is intentional
  (#161) — provisioning was previously ~50 % of cell wall-clock. If you
  want per-scenario isolation for debugging a flaky scenario, use
  `--scenario s2 --device desktop` to run just one cell in one
  container.
