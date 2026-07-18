# Azure provisioning for observability

One-time steps to stand up the Azure resources that make the RUM fabric work.
Production uses separate frontend and backend Application Insights components;
the canonical names live in `.github/azure-observability.env`.

**Prereqs:** you already have the App Services (`trainsight-app` and
`praxys-frontend` in `rg-trainsight`) plus the `log-trainsight` Log Analytics
workspace.

## Auth model summary

Two different auth paths and components in the same workspace, and that is
intentional:

- **Backend → `appi-praxys-backend`:** App Service system-assigned **managed
  identity**. Local authentication is disabled, so a browser-held
  instrumentation key cannot forge backend product or Coach events.
- **Browser → `appi-trainsight`:** build-time-embedded connection string as a
  write-only ingestion token (Microsoft's intended pattern — no MI flow exists
  for browsers). This component is treated as untrusted RUM.

Both components link to `log-trainsight`; component IDs and alert scopes preserve
the trust boundary inside the shared workspace.

## 1. Create the Application Insights resources

```bash
RG=rg-trainsight
WORKSPACE_ID=$(az monitor log-analytics workspace show \
  -g "$RG" -n log-trainsight --query id -o tsv)

# Frontend/RUM component. Existing production name is legacy but intentional.
az monitor app-insights component create \
  -g "$RG" -a appi-trainsight -l eastasia \
  --workspace "$WORKSPACE_ID" --kind web --application-type web
FRONTEND_ID=$(az resource show -g "$RG" -n appi-trainsight \
  --resource-type Microsoft.Insights/components --query id -o tsv)
az resource update --ids "$FRONTEND_ID" \
  --set properties.DisableLocalAuth=false tags.trustBoundary=frontend

# Backend-only component.
az monitor app-insights component create \
  -g "$RG" -a appi-praxys-backend -l eastasia \
  --workspace "$WORKSPACE_ID" --kind web --application-type web
BACKEND_ID=$(az resource show -g "$RG" -n appi-praxys-backend \
  --resource-type Microsoft.Insights/components --query id -o tsv)
az resource update --ids "$BACKEND_ID" \
  --set properties.DisableLocalAuth=true tags.trustBoundary=backend
```

Skip a `create` command when that component already exists. Do not copy either
connection string into GitHub settings; the deploy workflows fetch them through
Azure OIDC.

## 2. Enable system-assigned managed identity on App Service

1. Azure Portal → App Service `trainsight-app` → **Settings** → **Identity**.
2. **System assigned** tab → Status: **On** → Save → confirm.
3. Once enabled, the portal shows an **Object (principal) ID** — you'll need it in step 3. (The UI also offers direct "Azure role assignments" as a shortcut; step 3 uses the App Insights side of the assignment, which is simpler to reason about.)

## 3. Grant the App Service MI access to the backend component

1. Azure Portal → Application Insights `appi-praxys-backend` → **Access control (IAM)** → **Add** → **Add role assignment**.
2. **Role:** search for **Monitoring Metrics Publisher** → Next.
3. **Members:** **Managed identity** → **Select members** → App Service → `trainsight-app` → Select → Next.
4. Review + assign.
5. Propagation usually takes <60s; give it a minute before redeploying.

CLI equivalent:

```bash
MI=$(az webapp identity show -g rg-trainsight -n trainsight-app \
  --query principalId -o tsv)
az role assignment create \
  --assignee-object-id "$MI" \
  --assignee-principal-type ServicePrincipal \
  --role "Monitoring Metrics Publisher" \
  --scope "$BACKEND_ID"
```

> If you ever switch to user-assigned MI: also add `AZURE_CLIENT_ID` to app settings with the UAMI's client ID. The code picks it up automatically.

## 4. Let deployment own routing

Keep these names in `.github/azure-observability.env`. The backend workflow
fetches `appi-praxys-backend`'s connection string, verifies Entra-only
ingestion/RBAC, and writes the App Service setting. The frontend workflow fetches
only `appi-trainsight` and injects it into Vite. Do not create
`APPLICATIONINSIGHTS_CONNECTION_STRING` or
`VITE_APPINSIGHTS_CONNECTION_STRING` repository variables.

`api/main.py` uses `ManagedIdentityCredential`; the backend connection string
selects the endpoint/component but does not authenticate the exporter.

## 5. Kick a redeploy

Merge a change touching `.github/azure-observability.env`,
`scripts/appinsights_boundary.sh`, or either deploy workflow. Both deploys will
run.

## 6. Verify data is flowing

Wait 2–5 minutes after the deploys finish, then:

1. Browse the production site once — hit the homepage, log in, open Today, navigate to Training.
2. In `appi-trainsight` → **Logs**, run:
   ```kusto
   customMetrics
   | where name startswith "WebVitals."
   | order by timestamp desc
   | take 20
   ```
   You should see FCP / LCP / INP / CLS / TTFB events with `netinfo_effectiveType` / `netinfo_downlink` / `netinfo_rtt` in `customDimensions`. The telemetry initializer prefixes these with `netinfo_` to avoid shadowing SDK-native envelope fields — see the module header in `web/src/lib/appinsights.ts`.
3. In `appi-praxys-backend` → **Logs**, confirm server-side:
   ```kusto
   requests
   | where timestamp > ago(15m)
   | project timestamp, name, duration, resultCode, cloud_RoleName
   | order by timestamp desc
   | take 20
   ```

4. Re-run the enforced trust probe:
   ```bash
   set -a
   source .github/azure-observability.env
   set +a
   GITHUB_ENV=$(mktemp) bash scripts/appinsights_boundary.sh backend-preflight
   ```
   It must observe HTTP 401/403 when it attempts an anonymous forged
   `praxys.product_event`.

If either side is empty after 10 minutes, check the workflow, workspace linkage,
the exact-resource MI role assignment, and — for the frontend — that the
connection string made it into the built bundle (search `dist/assets/*.js` for
the ingestion endpoint hostname).

## 7. Create Standard availability tests

Always-on uptime + TTFB trend from Azure POPs. Free-ish (a few cents per month per test at 5-min cadence). Use **Standard tests**; the legacy "URL ping test" is retiring 30 Sept 2026.

1. Application Insights → **Availability** → **+ Add Standard test**.
2. Test 1: **Frontend homepage**
   - Name: `prod-homepage`
   - URL: `https://<your-custom-domain>/`
   - Test frequency: 5 minutes
   - Test locations: **West US**, **North Europe**, **East Asia** (three is fine — more just costs more without adding much signal for our use case)
   - Success criteria: HTTP 200, timeout 30s, parse dependent requests **off**
   - Alerts: enable, route to your email
3. Test 2: **Backend health endpoint**
   - Same settings but URL `https://<your-api-domain>/api/health`
4. Save both.

After 15 minutes you'll have first data points; after 24 hours you'll have usable trend lines on the Availability blade.

**Note:** Azure has no mainland China POPs, so these tests run from Hong Kong at closest. They complement but don't replace the WebPageTest probes run from inside mainland China — see `scripts/run-baseline.md`.

## 8. (Later) Dashboards

Once data's flowing, build an Azure Workbook that pivots by:
- `customDimensions.netinfo_effectiveType` — 4g / 3g / slow-2g / wifi (note the prefix — `effectiveType` on its own won't match)
- `client_CountryOrRegion` — CN vs rest
- `cloud_RoleName` — frontend vs backend
- Scenario (add a `scenario` custom dimension from client code if useful)

Can be scaffolded later — not blocking any Phase 1 fix.
