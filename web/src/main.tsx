import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nProvider } from '@lingui/react'
import './index.css'
import App from './App'
import { i18n, activateLocale, DEFAULT_LOCALE, isSupportedLocale, type SupportedLocale } from './i18n/init'
import { detectLocaleFromTag } from './lib/locale-detect'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 2 * 60 * 1000,
      gcTime: 5 * 60 * 1000,
      retry: 2,
      refetchOnWindowFocus: true,
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
  try {
    const stored = localStorage.getItem('trainsight-locale')
    if (isSupportedLocale(stored)) return stored
  } catch {
    // localStorage may be unavailable (private browsing, server-render)
  }
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
