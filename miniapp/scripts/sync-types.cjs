#!/usr/bin/env node
/*
 * Copy web/src/types/api.ts → miniapp/types/api.ts so the mini program
 * always sees the latest API contract from the web app.
 *
 * Bound to npm script `pretypecheck` so any `npm run typecheck` re-syncs
 * before tsc reads. Also runnable directly: `npm run sync-types`.
 *
 * If types diverge enough that mini-program-only fields are needed,
 * promote this to a workspace package — but right now the contract is
 * one-way: web is the source of truth, miniapp consumes a subset.
 */

const fs = require('fs');
const path = require('path');

const SRC = path.resolve(__dirname, '..', '..', 'web', 'src', 'types', 'api.ts');
const DEST = path.resolve(__dirname, '..', 'types', 'api.ts');

const HEADER =
  '// AUTO-SYNCED from web/src/types/api.ts by miniapp/scripts/sync-types.cjs.\n' +
  '// Edits here will be overwritten — change web/src/types/api.ts instead.\n\n';

function main() {
  if (!fs.existsSync(SRC)) {
    console.error(`[sync-types] source missing: ${SRC}`);
    process.exit(1);
  }
  fs.mkdirSync(path.dirname(DEST), { recursive: true });
  const body = fs.readFileSync(SRC, 'utf8');
  fs.writeFileSync(DEST, HEADER + body, 'utf8');
  const lineCount = body.split('\n').length;
  console.log(`[sync-types] wrote ${DEST} (${lineCount} lines)`);
}

main();
