import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nProvider } from '@lingui/react'
import './index.css'
import App from './App'
import { i18n, activateLocale, DEFAULT_LOCALE, isSupportedLocale, type SupportedLocale } from './i18n/init'
import { detectLocaleFromTag } from './lib/locale-detect'
import { KEYS, getCompatItem } from './lib/storage-compat'
import { initAppInsights } from './lib/appinsights'
import { registerSW } from 'virtual:pwa-register'

// Fire before render so the SDK captures the first page view + web vitals
// from the initial paint. No-op when VITE_APPINSIGHTS_CONNECTION_STRING
// is unset at build time.
initAppInsights()

// Register the service worker that vite-plugin-pwa generated. `immediate:
// true` activates the new SW as soon as it's installed, so a freshly-
// deployed version takes effect on the next navigation instead of after
// every open tab closes. onNeedRefresh / onOfflineReady are left as the
// default no-ops — we auto-update silently and don't prompt the user
// (matches registerType: 'autoUpdate' in vite.config.ts).
registerSW({ immediate: true })

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 2 * 60 * 1000,
      gcTime: 5 * 60 * 1000,
      retry: 2,
      // Disabled because CN users on spotty mobile network were burning
      // seconds of round-trips every time they tabbed back from WeChat
      // or another app. Stale data is refetched lazily via staleTime
      // expiration + manual refetch() calls already wired where it matters
      // (sync status polling, etc.). Leaving this on made the app feel
      // like it "reloaded for no reason" after an app switch.
      refetchOnWindowFocus: false,
    },
  },
})

// Pick the locale for first paint the same way LocaleProvider will, so
// returning zh users never see an EN flash before their stored preference
// kicks in. localStorage is authoritative; then navigator.language; then
// DEFAULT_LOCALE. The server-preference case (user changed language on
// another device) still falls back to LocaleSync after settings load —
// that's an unavoidable round-trip.
function _initialLocale(): SupportedLocale {
  const stored = getCompatItem(KEYS.locale.new, KEYS.locale.legacy)
  if (isSupportedLocale(stored)) return stored
  if (typeof navigator !== 'undefined') {
    return detectLocaleFromTag(navigator.language)
  }
  return DEFAULT_LOCALE
}

activateLocale(_initialLocale())

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <I18nProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </I18nProvider>
  </StrictMode>,
)
