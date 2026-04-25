import { useState } from 'react';
import { View, Text, Button } from '@tarojs/components';
import Taro, { useDidShow } from '@tarojs/taro';

import { useApi } from '@/hooks/useApi';
import { clearToken } from '@/lib/auth';
import {
  applyThemeChrome,
  getThemePreference,
  setThemePreference,
  themeClassName,
  type ThemePref,
} from '@/lib/theme';
import type { SettingsResponse } from '@/types/api';
import './index.scss';

// Hostname of the full web app. Hardcoded because it's stable per
// environment; if you later support multiple deployments, make this an
// API_BASE-neighbour env var.
const WEB_URL = 'https://www.praxys.run';

/**
 * Settings view — read-only for the MVP. Full editing (thresholds,
 * zones, goal, connections) continues to live on the web; the mini
 * program just surfaces the current values so users can verify their
 * config and know where to make changes.
 *
 * The sign-out button removes the JWT and returns to the login page.
 */
export default function SettingsPage() {
  const { data, loading, error, refetch } = useApi<SettingsResponse>('/api/settings');
  const [theme, setTheme] = useState<ThemePref>(getThemePreference());
  useDidShow(() => applyThemeChrome());

  function onSignOut() {
    clearToken();
    Taro.reLaunch({ url: '/pages/login/index' });
  }

  function onPickTheme(next: ThemePref) {
    if (next === theme) return;
    setThemePreference(next);
    setTheme(next);
    // Mini programs don't share a DOM across pages — every page has already
    // read the old preference during its mount. A reLaunch is the cleanest
    // way to force every page to re-evaluate themeClassName() and pick up
    // the new colours. Tiny UX cost (back to Today tab) in exchange for a
    // consistent, bug-free theme switch.
    Taro.reLaunch({ url: '/pages/today/index' });
  }

  if (loading && !data) {
    return (
      <View className={`settings-root ${themeClassName()}`}>
        <Text className="settings-header">Settings</Text>
        <View className="ts-card"><View className="ts-skeleton" /></View>
      </View>
    );
  }

  if (error) {
    return (
      <View className={`settings-root ${themeClassName()}`}>
        <Text className="settings-header ts-destructive">Failed to load</Text>
        <Text>{error}</Text>
        <Button className="ts-button" onClick={() => refetch()}>Retry</Button>
      </View>
    );
  }

  if (!data) return null;
  const { config, effective_thresholds } = data;

  // Always iterate the known threshold keys rather than whatever the
  // backend returns verbatim. The raw config.thresholds dict includes
  // meta fields like `source` that aren't thresholds and would otherwise
  // render as bogus rows.
  const KNOWN_THRESHOLDS = [
    'cp_watts',
    'lthr_bpm',
    'threshold_pace_sec_km',
    'max_hr_bpm',
    'rest_hr_bpm',
  ] as const;

  const thresholdEntries = KNOWN_THRESHOLDS.map((k) => {
    const fromEffective = effective_thresholds?.[k];
    if (fromEffective && fromEffective.value != null) return [k, fromEffective] as const;
    const fromConfig = config.thresholds?.[k];
    const value =
      typeof fromConfig === 'number' || typeof fromConfig === 'string'
        ? fromConfig
        : null;
    return [k, { value, origin: fromEffective?.origin ?? 'none' }] as const;
  });

  const anyThresholdSet = thresholdEntries.some(([, e]) => e.value != null);

  return (
    <View className={`settings-root ${themeClassName()}`}>
      <Text className="settings-header">Settings</Text>

      <View className="ts-card">
        <Text className="ts-section-label">Profile</Text>
        <Row label="Name" value={config.display_name || '—'} />
        <Row label="Units" value={config.unit_system} />
        <Row label="Training base" value={config.training_base} />
      </View>

      <View className="ts-card">
        <Text className="ts-section-label">Connections</Text>
        {config.connections.length === 0 ? (
          <Text className="settings-empty ts-muted">
            No platforms connected. Link Garmin / Stryd / Oura from the
            web app — their OAuth flows aren't supported in mini programs.
          </Text>
        ) : (
          <>
            {config.connections.map((c) => (
              <Row key={c} label={formatPlatform(c)} value="connected" />
            ))}
            <Text className="settings-hint ts-muted">
              Manage connections from the web app.
            </Text>
          </>
        )}
      </View>

      <View className="ts-card">
        <Text className="ts-section-label">Thresholds</Text>
        {anyThresholdSet ? (
          <>
            {thresholdEntries.map(([k, entry]) => (
              <ThresholdRow
                key={k}
                label={formatThresholdKey(k)}
                value={entry.value}
                unit={formatThresholdUnit(k)}
                origin={entry.origin}
              />
            ))}
            <Text className="settings-hint ts-muted">
              Auto-detected from synced fitness data; override on the web.
            </Text>
          </>
        ) : (
          <Text className="settings-empty ts-muted">
            No thresholds yet. Sync Garmin / Stryd data to auto-detect CP,
            LTHR, and pace — or enter values manually on the web.
          </Text>
        )}
      </View>

      <View className="ts-card settings-nav-card"
        onClick={() => Taro.navigateTo({ url: '/pages/science/index' })}
      >
        <View className="settings-nav-row">
          <View>
            <Text className="settings-nav-title">Training science</Text>
            <Text className="settings-nav-sub ts-muted">
              Browse the load / recovery / prediction / zone theories
            </Text>
          </View>
          <Text className="settings-nav-chevron ts-muted">›</Text>
        </View>
      </View>

      <View className="ts-card">
        <Text className="ts-section-label">Theme</Text>
        <View className="settings-theme-row">
          {(['auto', 'dark', 'light'] as const).map((t) => (
            <Text
              key={t}
              className={
                theme === t
                  ? 'settings-theme-opt settings-theme-opt--active'
                  : 'settings-theme-opt'
              }
              onClick={() => onPickTheme(t)}
            >
              {t === 'auto' ? 'Auto' : t === 'dark' ? 'Dark' : 'Light'}
            </Text>
          ))}
        </View>
        <Text className="settings-hint ts-muted">
          Auto follows your WeChat system theme. Changing this reloads the app.
        </Text>
      </View>

      <View className="ts-card">
        <Text className="ts-section-label">Full experience on web</Text>
        <Text className="settings-webhint">
          Connect platforms, edit zones, browse science theories, and see
          everything with charts. The mini program is a quick-glance
          companion.
        </Text>
        <Text className="settings-weburl ts-value">{WEB_URL}</Text>
        <Button
          className="ts-button ts-button--secondary"
          onClick={() => {
            Taro.setClipboardData({ data: WEB_URL });
            Taro.showToast({ title: 'URL copied', icon: 'success', duration: 1500 });
          }}
        >
          Copy web URL
        </Button>
      </View>

      <View className="ts-card">
        <Text className="ts-section-label">Session</Text>
        <Button
          className="ts-button ts-button--secondary"
          onClick={onSignOut}
        >
          Sign out
        </Button>
      </View>
    </View>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View className="settings-row">
      <Text className="settings-label ts-muted">{label}</Text>
      <Text className="settings-value ts-value">{value}</Text>
    </View>
  );
}

/**
 * Threshold rows show value + unit + optional origin badge (e.g. "stryd",
 * "garmin", "user"). Origin makes it clear when a number was auto-detected
 * from a synced platform vs manually entered.
 */
function ThresholdRow({
  label,
  value,
  unit,
  origin,
}: {
  label: string;
  value: number | string | null;
  unit: string;
  origin: string | null;
}) {
  const display = (() => {
    if (value == null || value === '') return '—';
    if (unit === 'min/km' && typeof value === 'number') {
      // value is sec/km; format as m:ss
      const m = Math.floor(value / 60);
      const s = Math.round(value % 60);
      return `${m}:${String(s).padStart(2, '0')} /km`;
    }
    if (typeof value === 'number') {
      return `${Math.round(value)} ${unit}`;
    }
    return `${value} ${unit}`;
  })();

  return (
    <View className="settings-row">
      <View>
        <Text className="settings-label ts-muted">{label}</Text>
        {origin && origin !== 'user' && (
          <Text className="settings-origin ts-muted">from {origin}</Text>
        )}
      </View>
      <Text className="settings-value ts-value">{display}</Text>
    </View>
  );
}

// Platform names in the API come through lowercase; capitalize for display.
function formatPlatform(key: string): string {
  return key.charAt(0).toUpperCase() + key.slice(1);
}

// Threshold keys arrive as snake_case with suffixes. A small map keeps the
// display names punchy without inventing abbreviations we don't own.
const THRESHOLD_LABEL: Record<string, string> = {
  cp_watts: 'CP',
  lthr_bpm: 'LTHR',
  threshold_pace_sec_km: 'Threshold pace',
  max_hr_bpm: 'Max HR',
};

const THRESHOLD_UNIT: Record<string, string> = {
  cp_watts: 'W',
  lthr_bpm: 'bpm',
  threshold_pace_sec_km: 'min/km',
  max_hr_bpm: 'bpm',
};

function formatThresholdKey(key: string): string {
  return THRESHOLD_LABEL[key] ?? key;
}

function formatThresholdUnit(key: string): string {
  return THRESHOLD_UNIT[key] ?? '';
}
