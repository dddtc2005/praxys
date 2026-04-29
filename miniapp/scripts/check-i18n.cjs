#!/usr/bin/env node
/*
 * i18n coverage detector for the mini program.
 *
 * Three passes; each prints findings, exit non-zero if anything fires:
 *
 *   1. Hardcoded text in WXML — element body text plus a known set of
 *      user-visible attribute values (title, placeholder, aria-label,
 *      confirm-text, cancel-text, x-label, y-label, …). Anything
 *      containing ASCII letters that isn't a single `{{…}}` binding
 *      gets reported. Allowlist below covers brand tokens, glyphs, etc.
 *
 *   2. `t(…)` / `tFmt(…)` keys whose zh translation is missing. Looks
 *      up in `utils/i18n-extra.ts` (mini-only overrides) and
 *      `utils/i18n-catalog.ts` (synced from web's lingui .po). Both
 *      missing → report.
 *
 *   3. Hardcoded English-looking string literals in TS files — only
 *      flagged when the literal looks like prose (length >= 6, has a
 *      space, has a 4+ letter word) and is NOT inside a t()/tFmt() call
 *      and NOT in the allowlist. Heuristic; same-line `// i18n-allow`
 *      silences a false positive.
 *
 * Wired into `npm run typecheck` via `pretypecheck` so CI catches gaps.
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SCAN_DIRS = ['pages', 'components', 'custom-tab-bar', 'utils'];

const SKIP_FILES = new Set([
  path.join(ROOT, 'utils', 'i18n-catalog.ts'),
  path.join(ROOT, 'utils', 'i18n-extra.ts'),
  path.join(ROOT, 'utils', 'i18n.ts'),
  path.join(ROOT, 'types', 'api.ts'),
]);

const BRAND_LITERALS = new Set([
  'Praxys', 'Pra', 'ys',
  'EN', '中',
  '›', '‹', '×', '+', '−', '→', '·', '•', '✓', '○', '▾', '▸',
  'x',
  'km', 'W', 'bpm', 'min', 'mi', 'sec',
]);

const TS_SKIP_PATTERNS = [
  /^https?:\/\//,
  /^\/[a-z][a-zA-Z0-9_/-]*$/,
  /^[a-z_]+:[a-z_]+/,
  /^[A-Z_][A-Z0-9_]+$/,
  /^#[0-9a-fA-F]{3,8}$/,
  /^[\d.,\s%]+$/,
  /^\{[^}]*\}$/,
  /^[a-zA-Z][a-zA-Z0-9_-]*$/,
  /^\[[a-z-]+\]\s/,                     // console log prefixes: "[settings] foo"
  /^rgba?\(/,                            // color literals: rgba(...) / rgb(...)
  /^\d+(?:px|rem|em|%)\s/,               // CSS shorthand: "11px sans-serif"
  /^\d+\s+\d+px\s/,                      // CSS font shorthand: "500 52px ..."
  /sans-serif|monospace|BlinkMacSystem|-apple-system/, // font stacks
  // Comma-separated lists of identifiers (mini-program observer keys,
  // class name lists). All tokens are bare identifiers.
  /^[a-zA-Z][a-zA-Z0-9_-]*(?:\s*,\s*[a-zA-Z][a-zA-Z0-9_-]*)+$/,
  // Class name strings: tokens delimited by spaces, each kebab-case
  // (commonly with `--modifier` suffix from BEM).
  /^[a-zA-Z][a-zA-Z0-9-]*(?:\s+[a-zA-Z][a-zA-Z0-9-]*)+$/,
  // Class name strings with leading whitespace (concatenated suffixes).
  /^\s+[a-zA-Z][a-zA-Z0-9-]*(?:\s+[a-zA-Z][a-zA-Z0-9-]*)*$/,
];

const TS_LITERAL_ALLOWLIST = new Set([
  'ts-warning', 'ts-primary', 'ts-destructive', 'ts-muted', 'ts-value', 'ts-section-label',
  'success', 'fail', 'none', 'shareAppMessage', 'shareTimeline', 'next', 'done',
  'auto', 'light', 'dark', 'theme-light', 'theme-dark', 'simple', 'advanced',
  'race', 'continuous', 'race_date', 'cp_milestone',
  'UNAUTHENTICATED', 'WECHAT_NO_LOGIN_CODE', 'WECHAT_NOT_CONFIGURED',
  'no-console', 'no-explicit-any',
]);

const USER_VISIBLE_ATTRS = new Set([
  'title', 'placeholder', 'aria-label', 'confirm-text', 'cancel-text',
  'x-label', 'y-label', 'headline', 'detail', 'tap-label',
  'right-text', 'subtitle', 'cta', 'data-label',
]);

function walk(dir, exts, out = []) {
  if (!fs.existsSync(dir)) return out;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue;
      walk(full, exts, out);
    } else if (entry.isFile()) {
      if (SKIP_FILES.has(full)) continue;
      if (exts.includes(path.extname(entry.name))) out.push(full);
    }
  }
  return out;
}

function relish(file) {
  return path.relative(ROOT, file).replace(/\\/g, '/');
}

function lineNumberOf(text, offset) {
  let line = 1;
  for (let i = 0; i < offset && i < text.length; i++) if (text[i] === '\n') line++;
  return line;
}

/**
 * For each match of `openRe` (an opener like `t(`), find the balanced
 * closing `)` while skipping string literals and nested parens, then
 * replace the entire span with whitespace (newlines preserved).
 *
 * Single forward pass — masking the outer call wipes nested calls in
 * place, so we never need to revisit an earlier offset.
 */
function maskBalancedCalls(text, openRe) {
  const re = new RegExp(openRe.source, 'g');
  const out = text.split('');
  let m;
  while ((m = re.exec(text))) {
    // If this opener was already masked by a prior outer call, skip.
    if (out[m.index] === ' ' || out[m.index] === '\n') continue;
    let i = m.index + m[0].length;
    let depth = 1;
    while (i < text.length && depth > 0) {
      const c = text[i];
      if (c === "'" || c === '"') {
        const quote = c;
        i++;
        while (i < text.length && text[i] !== quote) {
          if (text[i] === '\\') i += 2;
          else i++;
        }
        i++;
        continue;
      }
      if (c === '`') {
        i++;
        while (i < text.length && text[i] !== '`') {
          if (text[i] === '\\') i += 2;
          else i++;
        }
        i++;
        continue;
      }
      if (c === '(') depth++;
      else if (c === ')') depth--;
      i++;
    }
    if (depth !== 0) continue;
    for (let j = m.index; j < i; j++) {
      if (out[j] !== '\n') out[j] = ' ';
    }
  }
  return out.join('');
}

function unescapeStr(s) {
  return s
    .replace(/\\n/g, '\n')
    .replace(/\\t/g, '\t')
    .replace(/\\'/g, "'")
    .replace(/\\"/g, '"')
    .replace(/\\\\/g, '\\');
}

function loadCatalogKeys() {
  const collected = new Set();
  // i18n-catalog.ts: scoped to the `zh: {…}` block (catalog has both en
  //   and zh under a single I18N_CATALOG export, and we only care about zh).
  // i18n-extra.ts:  scan every `const ZH_…` per-section literal. The
  //   per-locale objects are split across multiple consts so each is
  //   small enough to spot duplicates in by hand; there's no single
  //   `zh: {…}` block to anchor on. Picking up every ZH_* literal is
  //   more robust.
  const catalogPath = path.join(ROOT, 'utils', 'i18n-catalog.ts');
  if (fs.existsSync(catalogPath)) {
    const txt = fs.readFileSync(catalogPath, 'utf8');
    const zhStart = txt.search(/(?:^|[^A-Za-z0-9_])(?:"zh"|zh)\s*:\s*\{/m);
    if (zhStart >= 0) extractKeysFromBlock(txt, zhStart, collected);
  }
  const extraPath = path.join(ROOT, 'utils', 'i18n-extra.ts');
  if (fs.existsSync(extraPath)) {
    const txt = fs.readFileSync(extraPath, 'utf8');
    const declRe = /\bconst\s+ZH_[A-Z0-9_]+\s*=\s*\{/g;
    let m;
    while ((m = declRe.exec(txt))) {
      extractKeysFromBlock(txt, m.index, collected);
    }
  }
  return collected;
}

function extractKeysFromBlock(txt, anchor, out) {
  const blockStart = txt.indexOf('{', anchor);
  if (blockStart < 0) return;
  let depth = 0;
  let blockEnd = -1;
  for (let i = blockStart; i < txt.length; i++) {
    const c = txt[i];
    if (c === '{') depth++;
    else if (c === '}') {
      depth--;
      if (depth === 0) { blockEnd = i; break; }
    }
  }
  if (blockEnd < 0) return;
  const block = txt.slice(blockStart, blockEnd + 1);
  const keyRe = /(?:^|\n|,|\{)\s*(?:'([^'\\]*(?:\\.[^'\\]*)*)'|"([^"\\]*(?:\\.[^"\\]*)*)"|([A-Za-z_$][A-Za-z0-9_$]*))\s*:/g;
  let m;
  while ((m = keyRe.exec(block))) {
    const key = unescapeStr(m[1] ?? m[2] ?? m[3] ?? '');
    if (key) out.add(key);
  }
}

function scanWxml(file, findings) {
  let txt = fs.readFileSync(file, 'utf8');
  txt = txt.replace(/<!--[\s\S]*?-->/g, (m) => m.replace(/[^\n]/g, ' '));

  const bodyRe = />([^<>{}]*?(?:\{\{[^}]*\}\}[^<>{}]*?)*)</g;
  let m;
  while ((m = bodyRe.exec(txt))) {
    const raw = m[1];
    if (!raw) continue;
    const stripped = raw.replace(/\{\{[^}]*\}\}/g, '').trim();
    if (!stripped) continue;
    if (!/[A-Za-z]{2,}/.test(stripped)) continue;
    if (BRAND_LITERALS.has(stripped)) continue;
    if (/^[\s·•›‹×→·\-_+]+$/.test(stripped)) continue;
    // Brand URLs — never translated.
    if (/^(?:www\.)?praxys\.run$/i.test(stripped)) continue;
    findings.push({
      file,
      line: lineNumberOf(txt, m.index + 1),
      kind: 'wxml-body',
      text: stripped,
    });
  }

  const attrRe = /([a-zA-Z][a-zA-Z0-9-]*)\s*=\s*"([^"]*)"/g;
  while ((m = attrRe.exec(txt))) {
    const name = m[1];
    if (!USER_VISIBLE_ATTRS.has(name)) continue;
    const value = m[2];
    if (!value) continue;
    if (/^\s*\{\{[\s\S]*\}\}\s*$/.test(value)) continue;
    if (!/[A-Za-z]{2,}/.test(value)) continue;
    if (BRAND_LITERALS.has(value.trim())) continue;
    const stripped = value.replace(/\{\{[^}]*\}\}/g, '').trim();
    if (!stripped) continue;
    if (!/[A-Za-z]{2,}/.test(stripped)) continue;
    if (BRAND_LITERALS.has(stripped)) continue;
    findings.push({
      file,
      line: lineNumberOf(txt, m.index),
      kind: 'wxml-attr',
      attr: name,
      text: value,
    });
  }
}

function scanTsKeys(file, findings, knownKeys) {
  const txt = fs.readFileSync(file, 'utf8');
  const callRe = /\bt(?:Fmt)?\s*\(\s*(?:'([^'\\]*(?:\\.[^'\\]*)*)'|"([^"\\]*(?:\\.[^"\\]*)*)")\s*[,)]/g;
  let m;
  while ((m = callRe.exec(txt))) {
    const key = unescapeStr(m[1] ?? m[2] ?? '');
    if (!key) continue;
    if (knownKeys.has(key)) continue;
    findings.push({
      file,
      line: lineNumberOf(txt, m.index),
      kind: 'missing-zh',
      text: key,
    });
  }
}

function scanTsLiterals(file, findings) {
  const txt = fs.readFileSync(file, 'utf8');
  let masked = txt;
  masked = masked.replace(/\/\*[\s\S]*?\*\//g, (s) => s.replace(/[^\n]/g, ' '));
  masked = masked.replace(/\/\/[^\n]*/g, (s) => s.replace(/[^\n]/g, ' '));
  // Mask `t(…)` and `tFmt(…)` calls — including nested calls like
  // `tFmt('Sleep Score vs {0}', t('Avg Power'))`. We do a balanced-paren
  // walk by hand; a regex can't handle arbitrary nesting cleanly.
  masked = maskBalancedCalls(masked, /\bt(?:Fmt)?\s*\(/g);
  masked = masked.replace(/^[\t ]*import[^;\n]*[;\n]/gm, (s) => s.replace(/[^\n]/g, ' '));
  masked = masked.replace(
    /^[\t ]*(?:type|interface)\s[\s\S]*?(?:^[\t ]*\}|\n;)/gm,
    (s) => s.replace(/[^\n]/g, ' '),
  );

  const litRe = /'((?:[^'\\\n]|\\[\s\S])*)'|"((?:[^"\\\n]|\\[\s\S])*)"/g;
  let m;
  while ((m = litRe.exec(masked))) {
    const value = unescapeStr(m[1] ?? m[2] ?? '');
    if (!value) continue;
    if (TS_LITERAL_ALLOWLIST.has(value)) continue;
    if (TS_SKIP_PATTERNS.some((re) => re.test(value))) continue;
    if (value.length < 4) continue;
    if (!/[A-Za-z]{4,}/.test(value)) continue;
    // Already-Chinese strings (CJK character anywhere) — these are
    // explicitly localized inline (typically `locale === 'zh' ? zh : en`
    // ternaries), so we don't expect them in the catalog.
    if (/[一-鿿]/.test(value)) continue;
    const looksProse =
      /\s/.test(value) || /[?!…]/.test(value) || /^[A-Z][a-z].*\s/.test(value);
    if (!looksProse) continue;
    const lineNum = lineNumberOf(masked, m.index);
    const lineText = txt.split('\n')[lineNum - 1] ?? '';
    if (/i18n-allow/.test(lineText)) continue;
    // Inline `locale === 'zh' ? '…zh…' : '…en…'` ternaries are common —
    // skip the en side if any of the 5 lines around (±2) contains a
    // CJK literal OR a `'zh' ?` ternary marker. Hand-written localized
    // fallbacks don't need catalog entries.
    const allLines = txt.split('\n');
    const lo = Math.max(0, lineNum - 3);
    const hi = Math.min(allLines.length, lineNum + 2);
    const window = allLines.slice(lo, hi).join('\n');
    if (/[一-鿿]/.test(window)) continue;
    if (/'zh'\s*\?/.test(window)) continue;
    // Throw new Error('…') — internal-only diagnostic, never displayed.
    if (/throw\s+new\s+\w*Error\s*\(/.test(lineText)) continue;
    findings.push({
      file,
      line: lineNum,
      kind: 'ts-literal',
      text: value,
    });
  }
}

function main() {
  const wxmlFiles = [];
  const tsFiles = [];
  for (const sub of SCAN_DIRS) {
    const full = path.join(ROOT, sub);
    walk(full, ['.wxml'], wxmlFiles);
    walk(full, ['.ts'], tsFiles);
  }

  const findings = [];
  for (const f of wxmlFiles) scanWxml(f, findings);
  const knownKeys = loadCatalogKeys();
  for (const f of tsFiles) scanTsKeys(f, findings, knownKeys);
  for (const f of tsFiles) scanTsLiterals(f, findings);

  const byKind = new Map();
  for (const f of findings) {
    if (!byKind.has(f.kind)) byKind.set(f.kind, []);
    byKind.get(f.kind).push(f);
  }

  let total = 0;
  for (const [kind, list] of byKind) {
    console.log(`\n[${kind}] ${list.length} finding(s):`);
    for (const f of list) {
      const where = `${relish(f.file)}:${f.line}`;
      const detail = f.attr ? `${f.attr}="${f.text}"` : f.text;
      console.log(`  ${where}  ${JSON.stringify(detail)}`);
      total++;
    }
  }

  if (total === 0) {
    console.log('[i18n-check] no findings — all surfaces translated.');
    process.exit(0);
  }
  console.log(`\n[i18n-check] ${total} finding(s) total. ` +
    `Wrap with t()/tFmt() and add zh entries (web .po or miniapp i18n-extra.ts).`);
  process.exit(1);
}

main();
