#!/usr/bin/env node
/*
 * Convert web's lingui .po catalogs (web/src/locales/{en,zh}/messages.po)
 * into a small TS module the miniapp can import: utils/i18n-catalog.ts.
 *
 * Why not consume .po at runtime? Mini programs ban file reads outside
 * the package and don't have a .po parser. A build-time sync gives us
 * a small JSON-shaped catalog with no runtime dependencies.
 *
 * Bound to npm script `pretypecheck` so any `npm run typecheck` re-syncs.
 *
 * Limitations:
 *   - msgid_plural / plural forms are dropped (we'd need ICU runtime).
 *     Affects ~5 strings; they fall back to msgid as the key/value.
 *   - Comments (#. / #:) are skipped.
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const SOURCES = {
  en: path.join(ROOT, 'web', 'src', 'locales', 'en', 'messages.po'),
  zh: path.join(ROOT, 'web', 'src', 'locales', 'zh', 'messages.po'),
};
const OUT = path.resolve(__dirname, '..', 'utils', 'i18n-catalog.ts');

function unescape(s) {
  return s
    .replace(/\\n/g, '\n')
    .replace(/\\t/g, '\t')
    .replace(/\\"/g, '"')
    .replace(/\\\\/g, '\\');
}

function parsePo(text) {
  const lines = text.split('\n');
  const out = {};
  let key = null;
  let val = null;
  let mode = null; // 'id' | 'str' | null

  const commit = () => {
    if (key !== null) {
      // Empty msgid is the .po header — drop it. Also drop strings
      // where translation is missing (msgstr is empty).
      if (key !== '' && val) out[key] = val;
    }
    key = null;
    val = null;
    mode = null;
  };

  for (const raw of lines) {
    const line = raw.trim();
    if (line === '' || line.startsWith('#')) {
      if (mode === 'str') commit();
      continue;
    }

    let m;
    if ((m = line.match(/^msgid\s+"(.*)"$/))) {
      if (mode === 'str') commit();
      key = m[1];
      val = null;
      mode = 'id';
      continue;
    }
    if ((m = line.match(/^msgid_plural\s+"(.*)"$/))) {
      // Plural forms not supported — skip and reset.
      key = null;
      val = null;
      mode = null;
      continue;
    }
    if ((m = line.match(/^msgstr\s+"(.*)"$/))) {
      val = m[1];
      mode = 'str';
      continue;
    }
    if ((m = line.match(/^msgstr\[\d+\]\s+"(.*)"$/))) {
      // Plural — drop.
      key = null;
      val = null;
      mode = null;
      continue;
    }
    // Continuation line: bare quoted string concatenates onto the
    // current key or value.
    if ((m = line.match(/^"(.*)"$/))) {
      if (mode === 'id') key = (key || '') + m[1];
      else if (mode === 'str') val = (val || '') + m[1];
    }
  }
  commit();

  for (const k of Object.keys(out)) {
    out[k] = unescape(out[k]);
  }
  return out;
}

function serializeCatalog(catalogs) {
  const header =
    '// AUTO-GENERATED from web/src/locales/{en,zh}/messages.po by\n' +
    '// miniapp/scripts/sync-i18n.cjs. Do not edit by hand — change the\n' +
    '// .po files (or add `t(key)` calls in the web app and re-run\n' +
    '// `lingui extract`), then re-sync with `npm run sync-i18n`.\n\n' +
    "export type Locale = 'en' | 'zh';\n\n" +
    'export const I18N_CATALOG: Record<Locale, Record<string, string>> = ';

  // JSON.stringify gives valid TS for object literals. Use 2-space indent
  // for diff-friendly output.
  return header + JSON.stringify(catalogs, null, 2) + ';\n';
}

function main() {
  const catalogs = {};
  for (const [locale, src] of Object.entries(SOURCES)) {
    if (!fs.existsSync(src)) {
      console.error(`[sync-i18n] missing: ${src}`);
      process.exit(1);
    }
    const text = fs.readFileSync(src, 'utf8');
    catalogs[locale] = parsePo(text);
    console.log(
      `[sync-i18n] ${locale}: ${Object.keys(catalogs[locale]).length} translations`,
    );
  }

  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, serializeCatalog(catalogs), 'utf8');
  console.log(`[sync-i18n] wrote ${OUT}`);
}

main();
