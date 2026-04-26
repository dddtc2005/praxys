# Perf-baseline CI — one-time setup

This documents the Azure resources + GitHub config that back `.github/workflows/perf-baseline.yml`. Everything here is **already provisioned on the `dddtc2005/praxys` repo** — this doc exists so a future operator (or a forked repo) knows how to reproduce it.

## What the workflow does

Trigger: **manual** (`workflow_dispatch`) only. Inputs: `reason`, `probe` (`all` / `eastasia` / `westus` / `northeurope`), `scenario` (`all` / `s1` / `s2` / `s3` / `s4`), `device` (`both` / `desktop` / `mobile`), `target_url`.

The workflow expands those inputs into a three-axis matrix (`scenario × probe × device`). With defaults (`scenario=all probe=all device=both`) one click produces 24 cells in a single workflow run, all running in parallel via GH Actions matrix (capped at 8 concurrent for ACI quota friendliness). Single-cell runs are still possible — set the specific axis values you want.

Per-cell flow:

1. Uses OIDC to log in to Azure with the same service principal `deploy-backend.yml` uses.
2. (For S1/S2/S3) Uploads `scripts/sitespeed_scripts/*.js` preScripts to a `scripts/` subfolder of the perfbaselines share.
3. Spins up an Azure Container Instance in the cell's region running `sitespeedio/sitespeed.io:latest` with the share mounted at `/sitespeed.io/out`.
4. Waits for the container to terminate by polling **`exitCode != null`** (not `state == "Terminated"` — that field is unreliable cross-region). 15-min hard timeout; on timeout, downloads whatever made it to the share anyway.
5. Downloads the cell's HARs back to the runner and uploads as a GH Actions artifact (`baseline-<cell>-<run-id>`).
6. Deletes the container + wipes the cell's path on the share (`if: always()` — runs even on cell failure).
7. A final summary job runs `scripts/analyze_baseline.py` across all cells in the run and uploads the populated markdown table as `baseline-combined-<run-id>`.

## Azure resources

All in `rg-trainsight`, subscription `3ff02750-211c-4579-94a6-8c9af4e6d891`.

| Resource | Name | Created via |
|---|---|---|
| Storage account | `stperftrainsight` (StorageV2, Standard_LRS, eastasia) | `az storage account create` |
| File share | `perfbaselines` (5 GB quota) | `az storage share-rm create` |

Cost: ~$0.05/month for the share at idle + $0.30/baseline in ACI compute at our cadence. Roughly **$1–3/month** total.

## Azure RBAC / auth

The workflow reuses the existing OIDC service principal that ships backend deploys (secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`). That SP already holds **Contributor on `rg-trainsight`**, which is sufficient for:
- `Microsoft.ContainerInstance/containerGroups/write` (create ACI)
- `Microsoft.Storage/storageAccounts/fileServices/shares/files/write` (mount share)
- `Microsoft.ContainerInstance/containerGroups/delete` (teardown)

No extra role assignments needed.

## GitHub secret

The workflow needs one additional secret beyond the OIDC trio:

- **`STORAGE_ACCOUNT_KEY`** — `key1` of `stperftrainsight`. Used to mount the Azure File share into the ACI container, and also to download/delete files from the runner.
  - Already set on `dddtc2005/praxys`.
  - To rotate: `az storage account keys renew --account-name stperftrainsight --key key1` then `gh secret set STORAGE_ACCOUNT_KEY --repo dddtc2005/praxys` with the new value.

## Reproducing from scratch

If you fork the repo or rebuild the environment:

```bash
# 1. Create the storage account + share
az storage account create \
  --subscription <sub> --resource-group <rg> \
  --name <account> --location eastasia \
  --sku Standard_LRS --kind StorageV2

az storage share-rm create \
  --subscription <sub> --resource-group <rg> \
  --storage-account <account> --name perfbaselines --quota 5

# 2. Get the key
KEY=$(az storage account keys list \
  --subscription <sub> --resource-group <rg> \
  --account-name <account> --query "[0].value" -o tsv)

# 3. Set the GH secret
echo "$KEY" | gh secret set STORAGE_ACCOUNT_KEY --repo <owner>/<repo>

# 4. Update the `env:` block at the top of
#    .github/workflows/perf-baseline.yml with your sub ID, RG name,
#    storage account name if different.
```

## Triggering a run

GitHub UI → Actions → "Perf Baseline (sitespeed.io via ACI)" → **Run workflow** → fill inputs → Run.

Or via CLI:

```bash
gh workflow run perf-baseline.yml --repo dddtc2005/praxys \
  -f reason="after phase 1 #1 (self-host fonts)" \
  -f probe=eastasia \
  -f device=both
```

Outputs land as GH Actions artifacts named `baseline-<scenario>-<probe>-<device>-<run-id>/`. Each run also produces a single `baseline-combined-<run-id>` artifact with the run's analyzed README pre-rendered.

For long-term references, **commit only the README** to `docs/perf-baselines/<YYYY-MM-DD>-<sha>/`. HARs and other heavy outputs are gitignored deliberately — see "HAR storage policy" below.

## HAR storage policy

Since the repo went public on 2026-04-26, raw HAR files are kept **out of the repo**. They contain HTTP request/response metadata including authorization headers (which had stale JWT bearer tokens before the JWT rotation that accompanied the public flip). HARs now live in two places:

1. **GitHub Actions artifacts** (`baseline-<cell>-<run-id>` and `baseline-combined-<run-id>`). 30-day retention, downloadable via the Actions UI or `gh run download <run-id>`. Sufficient for "I want to re-analyze the most recent sweep".
2. **Azure blob container `perfbaselines-archive`** on storage account `stperftrainsight` in `rg-trainsight`. Private, durable, requires az auth. Holds anything older than 30 days that's worth keeping. The pre-public bundle of all HARs that used to be committed is at `perfbaselines-HARs-pre-public-2026-04-26.tar.gz`.

To retrieve the pre-public archive (e.g. to re-analyze an old baseline against a current code change):

```bash
KEY=$(az storage account keys list -g rg-trainsight -n stperftrainsight --query "[0].value" -o tsv)
az storage blob download \
  --account-name stperftrainsight \
  --account-key "$KEY" \
  --container-name perfbaselines-archive \
  --name perfbaselines-HARs-pre-public-2026-04-26.tar.gz \
  --file ./pre-public-hars.tar.gz
tar xzf ./pre-public-hars.tar.gz   # extracts into docs/perf-baselines/<date>/...
python scripts/analyze_baseline.py --baseline-dir docs/perf-baselines/<date>-<sha>
```

The `.gitignore` rule `docs/perf-baselines/**/*.har` ensures these extracted HARs don't accidentally re-enter the repo on the next commit.

## Login-scripted scenarios (S1/S2/S3)

When `scenario` is `s1`, `s2`, or `s3`, the workflow uploads `scripts/sitespeed_scripts/*.js` to a `scripts/` subfolder of the same `perfbaselines` Azure File share before the ACI starts. The container mounts the share at `/sitespeed.io/out`, so the preScripts appear at `/sitespeed.io/out/scripts/<scenario>.js`. Sitespeed.io is then invoked with `--multi /sitespeed.io/out/scripts/<scenario>.js` instead of a target URL.

The preScripts read three env vars (passed via `az container create --environment-variables`):

- `PRAXYS_PERF_BASE_URL` — derived from the workflow's `target_url` input (trailing slash stripped, e.g. `https://www.praxys.run`).
- `PRAXYS_PERF_USER` — defaults to `demo@trainsight.dev` (public demo account, same one Landing's "Try the demo" CTA ships). Override via repo secret `PRAXYS_PERF_USER`.
- `PRAXYS_PERF_PASSWORD` — defaults to `demo`. Override via repo secret `PRAXYS_PERF_PASSWORD`.

The defaults match `scripts/sitespeed_runner.sh` so a cloud cell and a local cell of the same scenario measure the same flow against the same account.

## Known limitations

- **No mainland-China POPs.** Azure has none in the public cloud; closest is `eastasia` (Hong Kong). For CN-from-inside-the-GFW numbers keep using `scripts/sitespeed_runner.sh` on an operator PC.
- **Cost scales with cadence.** At a baseline-per-week cadence, ~$3/month. More frequent runs scale linearly on ACI compute.
