import { View, Text, Button } from '@tarojs/components';
import Taro from '@tarojs/taro';

import { useApi } from '@/hooks/useApi';
import { clearToken } from '@/lib/auth';
import type { SettingsResponse } from '@/types/api';
import './index.scss';

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

  function onSignOut() {
    clearToken();
    Taro.reLaunch({ url: '/pages/login/index' });
  }

  if (loading && !data) {
    return (
      <View className="settings-root">
        <Text className="settings-header">Settings</Text>
        <View className="ts-card"><View className="ts-skeleton" /></View>
      </View>
    );
  }

  if (error) {
    return (
      <View className="settings-root">
        <Text className="settings-header ts-destructive">Failed to load</Text>
        <Text>{error}</Text>
        <Button className="ts-button" onClick={() => refetch()}>Retry</Button>
      </View>
    );
  }

  if (!data) return null;
  const { config } = data;

  return (
    <View className="settings-root">
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
          <Text className="ts-muted">No platforms connected.</Text>
        ) : (
          config.connections.map((c) => (
            <Row key={c} label={c} value="connected" />
          ))
        )}
        <Text className="settings-hint ts-muted">
          Connect Garmin / Stryd / Oura on the web app — required OAuth flows
          aren't supported in mini programs.
        </Text>
      </View>

      {Object.keys(config.thresholds).length > 0 && (
        <View className="ts-card">
          <Text className="ts-section-label">Thresholds</Text>
          {Object.entries(config.thresholds).map(([k, v]) => (
            <Row key={k} label={k} value={String(v ?? '—')} />
          ))}
        </View>
      )}

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
