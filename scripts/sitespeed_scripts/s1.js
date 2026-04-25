/**
 * S1 — Cold first load of Today page (via login).
 *
 * Drives Chrome through:
 *   1. Navigate to /login (cold profile, no cache)
 *   2. Fill email + password from PRAXYS_PERF_USER / PRAXYS_PERF_PASSWORD
 *      env vars (defaults to the public demo account)
 *   3. Submit, wait for the SPA to redirect to /today
 *   4. Measure the navigation that lands on /today
 *
 * The login submit triggers the SPA's auth flow, which navigates to /today
 * on success. We wrap that with measure.start/stop so the resulting metrics
 * (FCP, LCP, TTI, etc.) describe "how long from login click to Today
 * paint" — i.e. what a real new user actually feels.
 *
 * Used by sitespeed.io's --multi mode:
 *   sitespeed.io --multi scripts/sitespeed_scripts/s1.js -n 3 \
 *     --outputFolder /sitespeed.io/out/s1-<probe>-<device>
 *
 * Reads PRAXYS_PERF_BASE_URL (defaults to https://www.praxys.run).
 */

module.exports = async function (context, commands) {
  const baseUrl = process.env.PRAXYS_PERF_BASE_URL || 'https://www.praxys.run';
  const user = process.env.PRAXYS_PERF_USER || 'demo@trainsight.dev';
  const password = process.env.PRAXYS_PERF_PASSWORD || 'demo';

  // Step 1 — get to the login form (not measured).
  await commands.navigate(`${baseUrl}/login`);
  await commands.wait.byId('login-email', 10000);

  // Step 2 — fill credentials. Form is empty on a fresh navigation; no
  // need to clear. Browser autofill is disabled in headless Chrome that
  // sitespeed.io ships, so this stays clean.
  await commands.click.byId('login-email');
  await commands.addText.byId(user, 'login-email');

  await commands.click.byId('login-password');
  await commands.addText.byId(password, 'login-password');

  // Step 3 — measure the click → /today navigation.
  await commands.measure.start('s1-today-via-login');
  await commands.click.bySelector('button[type="submit"]');
  // Wait until the SPA has actually transitioned to /today.
  await commands.wait.byCondition(
    'document.location.pathname === "/today"',
    30000,
  );
  // Give the rendered Today page a moment to settle so LCP fires.
  await commands.wait.byPageToComplete(15000);
  await commands.measure.stop();
};
