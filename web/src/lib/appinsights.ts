/**
 * Azure Application Insights + web-vitals wiring. No-op when
 * VITE_APPINSIGHTS_CONNECTION_STRING is not set at build time, so local
 * dev and un-instrumented previews never ship telemetry.
 *
 * What gets captured when enabled:
 *   - Auto page views + SPA route changes (enableAutoRouteTracking)
 *   - Uncaught exceptions
 *   - fetch / XHR dependencies — each API call gets its own timing span
 *     correlated to the server-side OTel trace via CORS correlation
 *     headers (server wiring lives in api/main.py)
 *   - Core Web Vitals (LCP, FCP, INP, CLS, TTFB) as custom metrics
 *
 * Every telemetry item is enriched with the current navigator.connection
 * snapshot so we can segment by effectiveType (4g / 3g / slow-2g) and
 * compare mainland-China-mobile reality against everyone else.
 *
 * Why a connection string and not managed identity: browsers are not
 * Azure workloads — there is no managed identity flow available to
 * client-side code. Microsoft's intended pattern for browser telemetry
 * is a build-time-embedded connection string, which acts as a write-
 * only ingestion token (rate-limited by resource quota; unable to read
 * anything back). The backend (api/main.py) uses managed identity.
 */
import { ApplicationInsights, type ITelemetryItem } from '@microsoft/applicationinsights-web'
import { onCLS, onFCP, onINP, onLCP, onTTFB, type Metric } from 'web-vitals'

const CONNECTION_STRING = import.meta.env.VITE_APPINSIGHTS_CONNECTION_STRING ?? ''

type NetworkConnection = {
  effectiveType?: string
  downlink?: number
  rtt?: number
  saveData?: boolean
}

let appInsights: ApplicationInsights | null = null

export function initAppInsights(): ApplicationInsights | null {
  if (!CONNECTION_STRING) return null
  if (appInsights) return appInsights

  appInsights = new ApplicationInsights({
    config: {
      connectionString: CONNECTION_STRING,
      enableAutoRouteTracking: true,
      enableCorsCorrelation: true,
      disableFetchTracking: false,
      disableAjaxTracking: false,
      autoTrackPageVisitTime: true,
    },
  })
  appInsights.loadAppInsights()
  appInsights.addTelemetryInitializer(attachNetworkContext)
  appInsights.trackPageView()
  reportWebVitals()

  return appInsights
}

export function getAppInsights(): ApplicationInsights | null {
  return appInsights
}

function getNetworkSnapshot(): NetworkConnection | null {
  const conn = (navigator as unknown as { connection?: NetworkConnection }).connection
  return conn ?? null
}

function attachNetworkContext(envelope: ITelemetryItem): void {
  const conn = getNetworkSnapshot()
  if (!conn) return
  // Prefix with netinfo_ so we don't shadow any field the SDK populates
  // on its own envelopes (e.g. dependency spans spread into baseData.
  // properties). Same prefix on trackMetric below keeps App Insights
  // queries consistent — filter on netinfo_effectiveType everywhere.
  const baseData = (envelope.baseData ??= {})
  baseData.properties = {
    ...(baseData.properties ?? {}),
    netinfo_effectiveType: conn.effectiveType,
    netinfo_downlink: conn.downlink,
    netinfo_rtt: conn.rtt,
    netinfo_saveData: conn.saveData,
  }
}

function reportWebVitals(): void {
  if (!appInsights) return
  const send = (metric: Metric): void => {
    const conn = getNetworkSnapshot() ?? {}
    appInsights!.trackMetric(
      { name: `WebVitals.${metric.name}`, average: metric.value },
      {
        rating: metric.rating,
        navigationType: metric.navigationType,
        id: metric.id,
        netinfo_effectiveType: conn.effectiveType,
        netinfo_downlink: conn.downlink,
        netinfo_rtt: conn.rtt,
      },
    )
  }
  onCLS(send)
  onFCP(send)
  onINP(send)
  onLCP(send)
  onTTFB(send)
}
