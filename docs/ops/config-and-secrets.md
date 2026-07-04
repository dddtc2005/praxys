# Configuration & secrets

> **Summary:** Every Praxys config value, **where it is set** (the source of
> truth), what consumes it, and how to rotate it.
> **Use when:** Adding/changing/rotating an env var, secret, or build variable —
> or debugging "I changed a setting in the portal and it reverted".

## The golden rule

The backend's App Service **application settings are owned by the deploy
workflow**, not the portal. `.github/workflows/deploy-backend.yml` → *Sync App
Service settings* runs `az webapp config appsettings set` on **every deploy**
with a fixed list sourced from GitHub Actions secrets/variables (plus a few
literals). **Editing those keys in the Azure Portal is transient — the next
deploy overwrites them.** To change one permanently, update the GitHub
secret/variable (or the workflow literal) and re-deploy.

## Where each thing lives

### GitHub Actions → Secrets
`Repo → Settings → Secrets and variables → Actions → Secrets`

| Secret | Purpose | Consumed by |
|---|---|---|
| `AZURE_CLIENT_ID` / `AZURE_TENANT_ID` / `AZURE_SUBSCRIPTION_ID` | OIDC login to Azure (no client secret) | all deploy workflows (`azure/login`) |
| `PRAXYS_JWT_SECRET` | JWT signing key | pushed to App Service setting by `deploy-backend.yml` |
| `WECHAT_MINIAPP_APPID` / `WECHAT_MINIAPP_SECRET` | WeChat Mini Program auth | App Service setting (backend) |
| `PRAXYS_SMTP_PASSWORD` | SMTP client authorization code (WeCom/Exmail) for verification + invitation emails. **Optional.** | App Service setting (backend) |
| `WECHAT_MINIAPP_UPLOAD_KEY` | Mini program CI upload key | `miniapp-publish.yml` |

### GitHub Actions → Variables
`… → Variables` (non-secret; build variables are inlined into the SPA and ship to browsers)

| Variable | Purpose | Consumed by |
|---|---|---|
| `VITE_API_URL` (`https://api.praxys.run`) | API base baked into the SPA | `deploy-frontend-appservice.yml` build |
| `VITE_APPINSIGHTS_CONNECTION_STRING` | Browser RUM | SPA build |
| `AZURE_AI_ENDPOINT` | Azure OpenAI endpoint for insights/triage | App Service setting + `i18n.yml` |
| `KEY_VAULT_URL` / `KEY_VAULT_KEY_NAME` | Key Vault + RSA key name | App Service setting |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | App Insights routing | App Service setting |
| `PRAXYS_FEEDBACK_BLOB_ACCOUNT_URL` (`https://stperftrainsight.blob.core.windows.net`) | Private Blob store for feedback screenshots (keyless via MI) | App Service setting (backend) |
| `PRAXYS_FEEDBACK_BLOB_CONTAINER` (`feedback-screenshots`) | Blob container for screenshots | App Service setting (backend) |
| `PRAXYS_SMTP_HOST` / `PRAXYS_SMTP_PORT` / `PRAXYS_SMTP_USER` / `PRAXYS_SMTP_FROM` / `PRAXYS_SMTP_STARTTLS` | SMTP transport for verification + invitation emails (non-secret; the password is the secret above). **Optional.** | App Service setting (backend) |
| `PRAXYS_APP_BASE_URL` (`https://praxys.run`) | Public origin for verify/invite links in those emails | App Service setting (backend) |

### Azure App Service → Application settings (backend `trainsight-app`)
Source of truth = `deploy-backend.yml`. Literals set inline: `DATA_DIR=/home/data`,
`WEBSITES_PORT=8000`, `SCM_DO_BUILD_DURING_DEPLOYMENT=true`,
`WEBSITE_HTTPLOGGING_RETENTION_DAYS=3`. Everything else comes from the
secrets/variables above.

### Azure Key Vault (`kv-trainsight`)
- RSA key `trainsight-master-key` — the master key that wraps the per-user
  Fernet data-encryption keys (DEKs) protecting platform credentials
  (`db/crypto.py`). The App Service MI has *Key Vault Crypto User*. **Not** a
  plain env var.

### Local development → `.env`
Local only; never committed. See [`.env.example`](../../.env.example) for the full
annotated list. Minimum: `PRAXYS_LOCAL_ENCRYPTION_KEY` (Fernet); `PRAXYS_ENV=development`
to boot without a JWT secret.

## Adding a NEW backend setting (checklist)

1. Read it in code via `os.environ` / `getenv_compat` (treat unset as a safe default).
2. Add it to `.env.example` (annotated) for local dev.
3. Add it to `deploy-backend.yml`: the `env:` block (from `secrets.*` or `vars.*`)
   **and** the `az webapp config appsettings set` arg list.
4. If it must be present, add it to the *required-settings* loop; if optional,
   **leave it out** of that loop so an unset value can't fail the deploy.
5. Create the GitHub secret (sensitive) or variable (non-sensitive).

> Example: the feedback → GitHub-issue settings (`PRAXYS_GITHUB_APP_*`,
> `PRAXYS_FEEDBACK_GITHUB_*`) follow exactly this pattern and are intentionally
> optional. (Added by the feedback feature — dddtc2005/praxys#328.)

### Feedback screenshot storage (Azure Blob, keyless)

Screenshots attached to feedback (issue #337) are stored **privately** in Blob
(reusing the `stperftrainsight` account). Auth is keyless via the backend's
system-assigned managed identity — no key or connection string. One-time infra:

```bash
# 1. Dedicated container (kept separate from the perf data in this account)
az storage container create --account-name stperftrainsight \
  --name feedback-screenshots --auth-mode login

# 2. Grant the app MI data access on JUST that container (least privilege)
MI=$(az webapp identity show -n trainsight-app -g rg-trainsight --query principalId -o tsv)
SUB=$(az account show --query id -o tsv)
az role assignment create --assignee-object-id "$MI" --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" \
  --scope "/subscriptions/$SUB/resourceGroups/rg-trainsight/providers/Microsoft.Storage/storageAccounts/stperftrainsight/blobServices/default/containers/feedback-screenshots"

# 3. Register the two non-secret GitHub Actions variables (the source of truth).
#    deploy-backend.yml syncs them to the App Service settings on the next deploy.
gh variable set PRAXYS_FEEDBACK_BLOB_ACCOUNT_URL --body "https://stperftrainsight.blob.core.windows.net"
gh variable set PRAXYS_FEEDBACK_BLOB_CONTAINER   --body "feedback-screenshots"
```

The two `PRAXYS_FEEDBACK_BLOB_*` variables above point the app at it. Unset them
and the app falls back to local filesystem storage under `DATA_DIR` (persistent
on `/home`, but not the recommended long-term home). `api/feedback_storage.py`
selects the backend and authenticates with `DefaultAzureCredential`.

### Self-registration gate + email

Opening self-registration is **runtime config, not a setting**: an admin toggles
it and sets the seat cap on the Admin page (persisted in the `app_config` DB table
via `api/app_config.py`). Nothing to deploy for that — see
[admin-tasks.md](./admin-tasks.md).

The *email* prerequisites ARE optional settings (tables above): the `PRAXYS_SMTP_*`
group + `PRAXYS_APP_BASE_URL`. They power (a) double-opt-in email verification for
code-less sign-ups and (b) emailing invitation codes to waitlist signups. Unset →
the app still works: codes are shown for the admin to copy/mailto by hand, and open
sign-ups are created verified (no ownership check possible). To provision (WeCom /
Tencent Exmail):

```bash
# 1. In the Exmail mailbox: 设置 → 账号 → enable POP3/IMAP/SMTP, then generate a
#    客户端授权码 (client authorization code) — that is PRAXYS_SMTP_PASSWORD.
# 2. Register the non-secret variables + the secret (source of truth):
gh variable set PRAXYS_SMTP_HOST     --body "smtp.exmail.qq.com"
gh variable set PRAXYS_SMTP_PORT     --body "465"
gh variable set PRAXYS_SMTP_USER     --body "no-reply@praxys.run"
gh variable set PRAXYS_SMTP_FROM     --body "Praxys <no-reply@praxys.run>"
gh variable set PRAXYS_APP_BASE_URL  --body "https://praxys.run"
gh secret   set PRAXYS_SMTP_PASSWORD --body "<客户端授权码>"
# 3. Re-deploy the backend — deploy-backend.yml syncs them to App Service.
```

Azure App Service blocks outbound port **25** but allows **465/587** to an
authenticated relay like Exmail. The `EmailSender` interface (`api/email_sender.py`)
is provider-agnostic, so Azure Communication Services (HTTPS) can be swapped in
later without touching call sites if SMTP is ever blocked or Exmail's daily cap is
outgrown.

## Rotation

| Value | How | Impact |
|---|---|---|
| `PRAXYS_JWT_SECRET` | New `secrets.PRAXYS_JWT_SECRET`, re-deploy backend | **All active sessions invalidated** — every user must log in again. |
| `WECHAT_MINIAPP_SECRET` | Rotate in mp.weixin.qq.com, update GitHub secret, re-deploy | Mini program auth briefly fails until deploy lands. |
| `WECHAT_MINIAPP_UPLOAD_KEY` | Regenerate in mp.weixin.qq.com, update GitHub secret | Only affects mini program CI publishing. |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Update variable, re-deploy | Telemetry routes to the new resource. |
| Feedback GitHub App key (`PRAXYS_GITHUB_APP_PRIVATE_KEY`) | Generate a new private key on the app, update the secret, re-deploy (rarely needed). Setup: [setup-github-app.md](./setup-github-app.md). | Issue auto-filing dormant until updated; rest of app unaffected. |
| SMTP auth code (`PRAXYS_SMTP_PASSWORD`) | Regenerate the 客户端授权码 in the Exmail/WeCom mailbox settings, update the GitHub secret, re-deploy. | Verification + invitation emails fail to send until updated (codes can still be copied by hand). |
| Key Vault RSA key `trainsight-master-key` | ⚠️ **High-impact** — the per-user DEKs were wrapped with the current key; rotating without a re-wrap/re-encrypt migration makes stored platform credentials undecryptable. **TODO(@dddtc2005):** document the re-wrap drill before rotating. | Users would have to reconnect platforms. |

## Related

- [deploy.md](./deploy.md) · [environment.md](./environment.md) · `docs/deployment.md`
- `.github/workflows/deploy-backend.yml` (source of truth for App Service settings)

---
_Last reviewed: 2026-07-04 · Owner: @dddtc2005_
