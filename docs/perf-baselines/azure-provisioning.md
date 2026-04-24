# Azure provisioning for observability

One-time steps to stand up the Azure resources that make the RUM fabric work. After these, redeploy frontend + backend once and data starts flowing.

**Prereqs:** you already have the App Service (`trainsight-app` in `rg-trainsight`) and the Static Web App live.

## Auth model summary

Two different auth paths in the same fabric, and that's intentional:

- **Backend → App Insights:** App Service system-assigned **managed identity**. No secret in app settings; the `APPLICATIONINSIGHTS_CONNECTION_STRING` env var is only used for routing (endpoint URL). Steps 2 + 4 below.
- **Browser → App Insights:** build-time-embedded **connection string** as a write-only ingestion token (Microsoft's intended pattern — no MI flow exists for browsers). Step 5 below.

Because the browser path needs ingestion-key auth, the App Insights resource **must leave local authentication enabled** (step 1d). Granting the backend a Monitor-Publisher role alongside doesn't weaken that; both paths coexist.

## 1. Create the Application Insights resource

1. Azure Portal → **Create a resource** → search **Application Insights** → Create.
2. Settings:
   - **Name:** `praxys-appinsights` (or your preference)
   - **Region:** **East Asia** (same as App Service — minimises ingestion latency)
   - **Resource group:** `rg-trainsight`
   - **Resource mode:** **Workspace-based** (the only supported mode — picks or creates a Log Analytics workspace)
   - **Log Analytics workspace:** create new `praxys-logs` in East Asia, or reuse an existing one
3. Review + Create.
4. Once deployed, open the resource → **Properties** blade → confirm **Local Authentication** is **Enabled**. Leave it as-is. (Disabling it would force AAD-only ingestion, which breaks the browser SDK — see auth model summary above.)
5. Open **Overview** → copy the **Connection String** (a long `InstrumentationKey=...;IngestionEndpoint=...;...` blob). You'll paste it into App Service and GitHub in the next steps.

## 2. Enable system-assigned managed identity on App Service

1. Azure Portal → App Service `trainsight-app` → **Settings** → **Identity**.
2. **System assigned** tab → Status: **On** → Save → confirm.
3. Once enabled, the portal shows an **Object (principal) ID** — you'll need it in step 3. (The UI also offers direct "Azure role assignments" as a shortcut; step 3 uses the App Insights side of the assignment, which is simpler to reason about.)

## 3. Grant the App Service MI the Monitoring Metrics Publisher role on App Insights

1. Azure Portal → Application Insights `praxys-appinsights` → **Access control (IAM)** → **Add** → **Add role assignment**.
2. **Role:** search for **Monitoring Metrics Publisher** → Next.
3. **Members:** **Managed identity** → **Select members** → App Service → `trainsight-app` → Select → Next.
4. Review + assign.
5. Propagation usually takes <60s; give it a minute before redeploying.

## 4. Wire the routing endpoint into App Service (backend)

Even with MI auth, the backend still needs to know _where_ to send telemetry — that's what the connection string is for.

1. App Service `trainsight-app` → **Settings** → **Environment variables** (or **Configuration** → **Application settings** on older portal UI).
2. Add:
   - **Name:** `APPLICATIONINSIGHTS_CONNECTION_STRING`
   - **Value:** the connection string from step 1.5
3. **Save** → confirm restart.

`api/main.py` detects that `WEBSITE_SITE_NAME` is set (→ we're on App Service) and calls `configure_azure_monitor(credential=ManagedIdentityCredential())`. The InstrumentationKey portion of the env var is used only to route; auth is an AAD token from the MI.

> If you ever switch to user-assigned MI: also add `AZURE_CLIENT_ID` to app settings with the UAMI's client ID. The code picks it up automatically.

## 5. Wire the connection string into GitHub (frontend)

The frontend value is a **repository variable**, not a secret — connection strings are write-only ingestion tokens and ship in every client bundle by design. Browsers have no MI path, so this is the correct pattern (see auth model summary above and the comment at the top of `web/src/lib/appinsights.ts`).

1. GitHub → `dddtc2005/praxys` → **Settings** → **Secrets and variables** → **Actions** → **Variables** tab.
2. **New repository variable:**
   - **Name:** `VITE_APPINSIGHTS_CONNECTION_STRING`
   - **Value:** the same connection string from step 1.5
3. Save.

The `.github/workflows/deploy-frontend.yml` workflow already references this variable in its `env:` block — the next deploy picks it up automatically.

## 6. Kick a redeploy

Easiest: push any small change that triggers both workflows, or manually trigger them via **Actions** tab → select workflow → **Run workflow** (the deploy backend workflow doesn't have a manual trigger yet, so the push route is simpler).

## 7. Verify data is flowing

Wait 2–5 minutes after the deploys finish, then:

1. Browse the production site once — hit the homepage, log in, open Today, navigate to Training.
2. Azure Portal → Application Insights `praxys-appinsights` → **Investigate** → **Live Metrics**. You should see the request come through in near real-time.
3. **Logs** blade, run:
   ```kusto
   customMetrics
   | where name startswith "WebVitals."
   | order by timestamp desc
   | take 20
   ```
   You should see FCP / LCP / INP / CLS / TTFB events with `netinfo_effectiveType` / `netinfo_downlink` / `netinfo_rtt` in `customDimensions`. The telemetry initializer prefixes these with `netinfo_` to avoid shadowing SDK-native envelope fields — see the module header in `web/src/lib/appinsights.ts`.
4. Confirm server-side:
   ```kusto
   requests
   | where timestamp > ago(15m)
   | project timestamp, name, duration, resultCode, cloud_RoleName
   | order by timestamp desc
   | take 20
   ```

If either side is empty after 10 minutes, check: env-var name spelling, workflow ran & succeeded, Python package install included `azure-monitor-opentelemetry`, MI role assignment propagated (check `AZ-ARM` logs if a `401` shows up on the exporter side), and — for the frontend — that the connection string made it into the built bundle (search `dist/assets/*.js` for the ingestion endpoint hostname).

## 8. Create Standard availability tests

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

## 9. (Later) Dashboards

Once data's flowing, build an Azure Workbook that pivots by:
- `customDimensions.netinfo_effectiveType` — 4g / 3g / slow-2g / wifi (note the prefix — `effectiveType` on its own won't match)
- `client_CountryOrRegion` — CN vs rest
- `cloud_RoleName` — frontend vs backend
- Scenario (add a `scenario` custom dimension from client code if useful)

Can be scaffolded later — not blocking any Phase 1 fix.
