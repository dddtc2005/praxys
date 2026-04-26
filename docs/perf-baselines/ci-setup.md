# Perf-baseline CI — one-time setup

This documents the Azure resources + GitHub config that back `.github/workflows/perf-baseline.yml`. Everything here is **already provisioned on the `dddtc2005/praxys` repo** — this doc exists so a future operator (or a forked repo) knows how to reproduce it.

## What the workflow does

Trigger: **manual** (`workflow_dispatch`) only. Inputs: `reason`, `probe` (Azure region — `eastasia` / `westus` / `northeurope`), `target_url`, `scenario` (`s1` / `s2` / `s3` / `s4`), `device`.

1. Uses OIDC to log in to Azure with the same service principal `deploy-backend.yml` uses.
2. Spins up an Azure Container Instance in the chosen region running `sitespeedio/sitespeed.io:latest`.
3. ACI mounts an Azure Files share at `/sitespeed.io/out` so the HAR + browsertime output lands somewhere durable.
4. Polls until the container exits, dumps its stdout log, then downloads the HARs from the share back to the GH runner.
5. Uploads a GH Actions artifact per cell (one per probe × device pair in the matrix).
6. Deletes the container + wipes the share path so nothing accumulates.
7. A final summary job runs `scripts/analyze_baseline.py` across all cells and uploads the populated markdown table as its own artifact.

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

Outputs land as GH Actions artifacts named `baseline-<scenario>-<probe>-<device>-<run-id>/`. Download + merge into a `docs/perf-baselines/<YYYY-MM-DD>-<sha>/` directory per the `README.md` / `TEMPLATE.md` convention.

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
