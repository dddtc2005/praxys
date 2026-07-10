# Rotate a secret

> **Summary:** Rotate the app's secrets safely, with the blast radius of each.
> **Use when:** Scheduled rotation, suspected compromise, or offboarding.

The source of truth for backend secrets is the **GitHub Actions secret** → pushed
to App Service on deploy (see [config-and-secrets.md](./config-and-secrets.md)).
General shape: update the GitHub secret → re-deploy → verify → invalidate the old.

## `PRAXYS_JWT_SECRET` — JWT signing key

**Blast radius: high — every active session is invalidated; all users must log in
again.** Schedule for a low-traffic window.

```bash
NEW=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
printf '%s' "$NEW" | gh secret set PRAXYS_JWT_SECRET --repo praxys-run/praxys
gh workflow run deploy-backend.yml --ref main
```
Verify: log in fresh; existing tokens now 401 (expected).

## `WECHAT_MINIAPP_SECRET`

Rotate in mp.weixin.qq.com → 开发设置, then:
```bash
printf '%s' '<NEW_SECRET>' | gh secret set WECHAT_MINIAPP_SECRET --repo praxys-run/praxys
gh workflow run deploy-backend.yml --ref main
```
Blast radius: WeChat mini-program login briefly fails until the deploy lands.

## `PRAXYS_GITHUB_APP_PRIVATE_KEY` — feedback App key

Generate a new private key on the GitHub App, set the secret from the new `.pem`,
re-deploy. Blast radius: low — only feedback auto-filing; reports still park for
admin. Steps: [setup-github-app.md](./setup-github-app.md) (step 3). Delete the
old key from the app afterwards.

## `COPILOT_ASSIGN_TOKEN` — change-loop assignment PAT

Fine-grained PAT (resource owner `praxys-run`, repo `praxys`, *Issues: read/write*)
that lets `assign-copilot.yml` hand an `agent-ready` issue to the Copilot coding
agent. **No auto-rotation** — fine-grained PATs simply expire. **Blast radius:
low** — only auto-assignment, and if it lapses the workflow *fails loudly*
(comments "assign manually" on the issue), so the change loop degrades to manual
assignment rather than breaking silently.

```bash
# mint a new fine-grained PAT (praxys-run/praxys, Issues: RW, ~90d expiry), then:
gh secret set COPILOT_ASSIGN_TOKEN -R praxys-run/praxys
```
Rotate ~every 90 days (calendar it). See [change-loop.md](./change-loop.md) §3.

## Key Vault RSA key `trainsight-master-key`

**Blast radius: critical — DO NOT rotate casually.** This master key wraps every
user's data-encryption key; rotating without a re-wrap migration makes stored
platform credentials undecryptable (users would have to reconnect platforms).

**TODO(@dddtc2005):** document + script the re-wrap drill (enumerate users,
unwrap DEK with the old key version, re-wrap with the new) before any rotation.
Until then, treat this key as non-rotatable.

## OIDC (`AZURE_CLIENT_ID` / federated credential)

Managed by the `trainsight-cicd` app registration (no client secret — OIDC). To
rotate trust, update the federated credential subject; see `docs/deployment.md`.

## Related

- [config-and-secrets.md](./config-and-secrets.md) (where each lives) · [deploy.md](./deploy.md)

---
_Last reviewed: 2026-06-30 · Owner: @dddtc2005_
