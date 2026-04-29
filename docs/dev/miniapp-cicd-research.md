# WeChat Mini Program CI/CD & Versioning — Research

**Status:** Research / proposal. No code wired yet.
**Question:** Can we replace the manual "上传" click in 微信开发者工具 with a CI/CD or API-driven publish, and version the mini program properly?

## TL;DR

Yes. Tencent ships an official, supported npm package — **`miniprogram-ci`** — that does *exactly* what the "上传" / "预览" buttons in DevTools do, headlessly. We can drive it from a GitHub Actions workflow on every push (or tag), with the project AppID + a private key stored as repo secrets.

| Stage | Automatable? | How |
|---|---|---|
| Upload to **开发版** (dev) | ✅ fully | `ci.upload({ robot: N, version, desc })` |
| Generate preview QR (临时预览) | ✅ fully | `ci.preview()` |
| Promote 开发版 → **体验版** (trial) | ⚠️ admin click | mp.weixin.qq.com → 版本管理 → "选为体验版" (trivial, ~2 sec) |
| **提交审核** (submit for audit) | ❌ self-hosted apps only via web | WeChat exposes `code/submit_audit` only to 第三方平台 / 服务商, not to first-party operators |
| **发布** to 正式版 (release) | ❌ self-hosted apps only via web | Same — manual click, gated on 审核 anyway |

**Net win:** every code change gets a versioned 开发版 in WeChat with a proper version string and changelog, no laptop with DevTools required. Promoting that to 体验版 / submitting for review remains a 2-click manual step (which we already have to do because audit is human-reviewed and takes 1–7 days).

---

## 1. The `miniprogram-ci` package

- npm: `miniprogram-ci` (Tencent-maintained, latest 2.1.x as of early 2026)
- Node.js library + CLI; same compile pipeline as DevTools
- Capabilities: `upload`, `preview`, `packNpm`, `getDevSourceMap`, cloud function deploys (we don't use those)
- Source: [WeChat official CI docs](https://developers.weixin.qq.com/miniprogram/dev/devtools/ci.html)

### Minimal upload sketch
```js
const ci = require('miniprogram-ci');

const project = new ci.Project({
  appid: process.env.WECHAT_MINIAPP_APPID,
  type: 'miniProgram',
  projectPath: './miniapp',                              // our miniapp/ directory
  privateKeyPath: './private.key',                        // injected from secret
  ignores: ['node_modules/**/*', '.github/**/*'],
});

await ci.upload({
  project,
  version: '0.3.1',                                       // shown in 版本管理
  desc: `${process.env.GITHUB_SHA.slice(0,7)} — ${process.env.COMMIT_MSG}`,
  setting: { es6: true, minify: true, codeProtect: false, autoPrefixWXSS: true },
  robot: 1,                                               // see §3
  threads: 4,
});
```

---

## 2. Versioning model — CalVer, per-component tags

WeChat does not enforce a version format — whatever string we pass to `ci.upload({ version, desc })` is shown verbatim in 版本管理. So we pick the scheme that matches how Praxys actually ships.

**Decision: CalVer (`YYYY.MM.MICRO`), per-component tags.**

The three components (backend, web, miniapp) ship at different cadences, so each gets its own tag namespace:

| Component | Tag pattern | Example |
|---|---|---|
| Mini program | `miniapp-YYYY.MM.MICRO` | `miniapp-2026.04.1` |
| Web frontend | `web-YYYY.MM.MICRO` | `web-2026.04.1` |
| Backend API | `api-YYYY.MM.MICRO` | `api-2026.04.1` |

`MICRO` increments within a calendar month; reset to `1` at the start of the next month. Multiple ships per month → `2026.04.1`, `2026.04.2`, `2026.04.3`. First ship in May → `2026.05.1`.

**Why CalVer over semver here:** Praxys components are deployed apps, not libraries — there's no external consumer reading a version to decide compatibility, so semver's "MAJOR vs MINOR vs PATCH" judgment calls add overhead without value. CalVer encodes "when did this ship," which is what we actually want to know when debugging "what's running in 体验版?"

**Dev / non-tag pushes** to `main` get a synthetic version: `YYYY.MM.DD.<run_number>+<sha7>` (e.g., `2026.04.29.42+abc1234`). This goes to robot 5, separate from the tag release line on robot 1, so dev iteration never overwrites the release candidate.

**`miniapp/package.json` `version` field** stays as a project-marker (currently `0.2.0`); the publish workflow does **not** read it. Tags are the source of truth. This removes the "did I remember to bump package.json?" failure mode.

This scheme extends naturally to `web/` and `api/` whenever we wire up automated deploys for those — same prefix-based tag pattern, separate workflows, independent cadences.

---

## 3. The "robot" model — important to internalize

`robot` is `1..30`. **Each robot is a separate slot in 版本管理**. Each robot keeps the *latest* version it uploaded; uploading again with the same robot overwrites that robot's 开发版. mp.weixin.qq.com only allows **one 体验版 globally**, but you choose which robot's 开发版 is currently selected as the 体验版.

Practical consequence:
- Different branches / environments → different robots → independent 开发版 slots that don't clobber each other
- Recommended mapping for Praxys (we have one mini program, a few branches):

| Robot | Purpose | Trigger |
|---|---|---|
| 1 | Release candidate (will become 体验版 → 正式版) | Tag `miniapp-v*` |
| 5 | Main branch dev | Push to `main` |
| 10 | Per-PR preview | PR opened/updated (use `ci.preview()` not upload, generates QR) |

Each robot upload is logged in 版本管理 with the robot index + commit-derived `desc`, so we can see who uploaded what.

---

## 4. One-time setup checklist

These steps happen **once**, by the mini program admin (Feitao):

1. **Generate the upload private key**
   - Log in to [mp.weixin.qq.com](https://mp.weixin.qq.com) → 开发管理 → 开发设置 → 小程序代码上传 (scroll near bottom)
   - Click "生成" — downloads `private.<appid>.key` (a PEM-style RSA private key, ~1.7 KB)
   - **This is a credential** — treat like a deploy key. Anyone with this file + the AppID can publish to our mini program

2. **Configure IP whitelist** (recommended) or disable it
   - Same panel; either:
     - Whitelist GitHub Actions runner IPs — but those are **dynamic**, this isn't practical for hosted runners. You'd need a self-hosted runner with a fixed egress IP.
     - **Disable the whitelist** entirely (option labelled 关闭IP白名单). The private key alone gates access.
   - For Praxys we should disable IP whitelist (we don't have self-hosted runners) and rely on the secret. WeChat's own docs explicitly support this trade-off.

3. **Add GitHub Actions secrets** (under repo Settings → Secrets and variables → Actions):
   - `WECHAT_MINIAPP_APPID` — the AppID `wx65e36494e7cf3ffb` (note: this is already in `miniapp/project.config.json` and isn't really sensitive, but keeping it as a secret matches the existing backend `.env` convention)
   - `WECHAT_MINIAPP_UPLOAD_KEY` — paste the contents of `private.<appid>.key`. CI will write it back to a temp file at runtime.

---

## 5. GitHub Actions workflow

The actual implementation lives at **`.github/workflows/miniapp-publish.yml`** in this branch — see that file for the canonical YAML. High-level shape:

- **Triggers:** push to `main` (path-gated by inline `git diff` since GitHub's `paths:` filter doesn't compose cleanly with tag triggers), tag pushes matching `miniapp-*`, and `workflow_dispatch` for manual reruns.
- **Gate step decides** whether to run: tag push → always; manual → always; main push → only if any of `miniapp/**`, `web/src/locales/**`, `web/src/types/api.ts`, or the workflow file itself changed in `HEAD^..HEAD`.
- **Always run typecheck first** (`npm run typecheck` includes `sync-types` + `sync-i18n` + `tsc`). A typecheck failure aborts the upload — we never publish a broken build.
- **Robot + version** chosen by the meta step:
  - `refs/tags/miniapp-2026.04.1` → robot 1, version `2026.04.1`, desc `release 2026.04.1`
  - main push → robot 5, version `YYYY.MM.DD.<run_number>+<sha7>`, desc `main <sha7>`
- **Upload step** uses `miniprogram-ci` with `setting.uploadWithSourceMap: true` so server-side stack traces remain useful. Result JSON (compiled package sizes, etc.) is logged.
- **Job summary** writes a markdown table to GitHub Actions UI showing trigger / robot / version / desc / ref / sha for at-a-glance audit.

**To release miniapp 2026.04.1:**
```bash
git tag miniapp-2026.04.1
git push origin miniapp-2026.04.1
# → workflow runs, robot 1's 开发版 in 版本管理 becomes 2026.04.1
# → in mp.weixin.qq.com 版本管理: click "选为体验版" on robot 1's row
# → scan QR with WeChat, verify
# → click "提交审核" → wait for review → click "发布"
```

**For PR previews (future):** add a job triggered on `pull_request` that calls `ci.preview()` with `qrcodeOutputDest: '$RUNNER_TEMP/preview.png'` on robot 10, then uploads the QR as an artifact and posts it as a PR comment. Not in scope for the first iteration.

---

## 6. What stays manual

- **审核 → 发布**: For self-hosted mini programs (i.e., us, not 第三方平台 service providers), the WeChat openapi `code/submit_audit` and `code/release` are gated to 服务商 accounts. A first-party operator must click "提交审核" and then "发布" in the admin web UI. This is unavoidable; audit is a human review (1–7 days) so it isn't actually a CI bottleneck.
- **Selecting which 开发版 is the 体验版**: One click in 版本管理. Doable via the same 服务商 API, same constraint.
- **Renaming a robot's developer label**: No public API; cosmetic only.

In practice the manual surface shrinks from "every dev iteration requires opening DevTools and clicking 上传" to "once per release, click 提交审核 → wait → click 发布."

---

## 7. Risks and gotchas

1. **The private key is high-value.** Anyone who exfiltrates `WECHAT_MINIAPP_UPLOAD_KEY` can publish to our mini program. Treat like prod DB credentials. Rotate via the same admin panel ("重置" button).
2. **`miniprogram-ci` does its own compile.** It will re-compile TS/Sass internally — *not* using the WeChat DevTools `useCompilerPlugins` setting. Confirm before first run that there's no behavior gap with what DevTools produces. The existing `miniapp-build.yml` doesn't actually compile the project (only typechecks), so the first CI upload is the first time we'll see what `miniprogram-ci`'s output looks like in 体验版.
3. **Source-map upload setting**: `project.config.json` has `"uploadWithSourceMap": true`. `miniprogram-ci` honors this only if we set `setting: { uploadWithSourceMap: true }` explicitly (it doesn't read `project.config.json` for everything). Add to the `setting` block above if we want sourcemaps in the WeChat error logs.
4. **`packNpm`**: WeChat needs `npm run miniprogram-ci` style npm-build for any miniapp `npm` deps. Praxys mini program has no runtime npm deps (devDeps only — `miniprogram-api-typings`, `typescript`), so we can skip `ci.packNpm()`. If we ever add a runtime dep like `weui-miniprogram`, add a `ci.packNpm()` call before `ci.upload()`.
5. **2 MB main package limit** still applies — `miniapp-build.yml` already guards on raw source size. After first CI upload, watch the actual compiled size in `ci.upload()`'s response (it returns `subPackageInfo[]` with byte counts).
6. **Robot collision with manual uploads**: If Feitao continues to "上传" via DevTools while CI runs, both sides may be writing to the same robot slot (DevTools defaults to a per-developer robot, but there's only one 体验版). Either: (a) reserve robots 1 & 5 exclusively for CI and document "humans use robot 30 in DevTools", or (b) stop using manual upload for the project entirely once CI works.

---

## 8. Comparison to status quo

| Dimension | Current (manual DevTools) | Proposed (miniprogram-ci) |
|---|---|---|
| Trigger | Open DevTools, click 上传, fill version + desc | `git push` |
| Reproducibility | Depends on local DevTools version, OS, plugins | CI sets exact Node + CLI version |
| Version discipline | Whatever the human types | Derived from `package.json` + tags |
| Audit trail | DevTools logs (local) | GitHub Actions run + `desc` carries SHA |
| Multi-developer | Each developer = separate 开发版, easy to lose track | One robot per environment, deterministic slots |
| Speed of dev → 体验版 | Manual (5 min context switch) | Automatic on push to main |
| 提交审核 → 发布 | Manual click | Still manual click (audit is human anyway) |

---

## 9. Status / next steps

Done:
- [x] IP whitelist disabled in mp.weixin.qq.com
- [x] `WECHAT_MINIAPP_APPID` + `WECHAT_MINIAPP_UPLOAD_KEY` added as repo secrets
- [x] `.github/workflows/miniapp-publish.yml` drafted in this branch
- [x] Versioning scheme decided (CalVer, per-component tags)

To do:
1. Review the workflow file diff, merge the branch.
2. **Dry-run on `main`**: push any miniapp-touching commit to `main`; watch Actions. Should upload to robot 5 with version `2026.04.29.X+<sha>`. Verify a 开发版 appears in 版本管理 row "robot 5."
3. **Dry-run a tag**: `git tag miniapp-2026.04.1 && git push origin miniapp-2026.04.1`. Robot 1 should get 开发版 `2026.04.1`. Promote to 体验版; scan QR; smoke-test.
4. After successful first 体验版 from CI, update `miniapp-build.yml`'s comment ("we can't run `miniprogram-ci` without the platform secret") — it's now outdated. Replace with a link to the publish workflow.
5. Add a one-liner to `trail-running/CLAUDE.md` mini program section pointing to this doc + the workflow.
6. (Later) Add a `pull_request` job for PR previews on robot 10 (`ci.preview()` + QR artifact + PR comment).

---

## Sources

- [WeChat official miniprogram-ci docs](https://developers.weixin.qq.com/miniprogram/dev/devtools/ci.html)
- [echoings/actions.mini-program (GitHub Action wrapper)](https://github.com/echoings/actions.mini-program)
- [WeChat community: 开发版 / 体验版 / 正式版 区别](https://developers.weixin.qq.com/community/minihome/doc/00020c26fd8030b0963d9a8f050000)
- [小程序发布了 miniprogram-ci](https://developers.weixin.qq.com/community/develop/article/doc/000aea788a4ae0354ec85c57e56c13)
- [Taro plugin-mini-ci docs (cross-platform wrapper, not used by us but informative)](https://nervjs.github.io/taro-docs/en/docs/plugin-mini-ci/)
