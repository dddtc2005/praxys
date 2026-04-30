/**
 * Frontend build version.
 *
 * Vite bakes ``VITE_APP_VERSION`` into the bundle at build time
 * (``deploy-frontend-appservice.yml`` injects ``YYYY.MM.DD.<run>-<sha>``
 * for auto-deploys; tagged releases like ``web-2026.05.1`` strip the
 * prefix). When unset — local ``npm run dev``, ``npm run build`` without
 * the env, or any consumer outside the deploy pipeline — we fall back to
 * the literal ``"develop"`` so the Settings line still renders, mirroring
 * the mini program's ``envVersion === 'develop'`` branch.
 */
export const WEB_VERSION: string =
  (import.meta.env.VITE_APP_VERSION as string | undefined)?.trim() || 'develop';
