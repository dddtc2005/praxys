import { View, Text, Button } from '@tarojs/components';
import { useDidShow } from '@tarojs/taro';

import { useApi } from '@/hooks/useApi';
import type { ScienceResponse, SciencePillar, TheorySummary } from '@/types/api';
import { applyThemeChrome, themeClassName } from '@/lib/theme';
import './index.scss';

/**
 * Training-science browser. Displays the active theory for each of the
 * four pillars (load / recovery / prediction / zones) plus the full list
 * of available alternatives.
 *
 * Read-only for the MVP — changing the active theory is a deliberate
 * decision that's better done on the full web UI (requires confirming
 * model impacts on existing data). The mini program's job is "help me
 * understand what my app is computing."
 */

const PILLAR_LABELS: Record<SciencePillar, string> = {
  load: 'Training load',
  recovery: 'Recovery',
  prediction: 'Race prediction',
  zones: 'Zones',
};

const PILLAR_DESCRIPTIONS: Record<SciencePillar, string> = {
  load: 'How fitness (CTL), fatigue (ATL), and form (TSB) are computed from each workout.',
  recovery: 'How daily recovery is assessed from HRV, sleep, and resting HR.',
  prediction: 'The model used to predict race times from your current CP/threshold.',
  zones: 'Which zone framework splits your training intensity distribution.',
};

export default function SciencePage() {
  const { data, loading, error, refetch } = useApi<ScienceResponse>('/api/science');
  useDidShow(() => applyThemeChrome());

  if (loading && !data) {
    return (
      <View className={`sci-root ${themeClassName()}`}>
        <View className="ts-card"><View className="ts-skeleton" /></View>
        <View className="ts-card"><View className="ts-skeleton" /></View>
      </View>
    );
  }

  if (error) {
    return (
      <View className={`sci-root ${themeClassName()}`}>
        <Text className="sci-header ts-destructive">Failed to load</Text>
        <Text className="ts-muted">{error}</Text>
        <Button className="ts-button" onClick={() => refetch()}>Retry</Button>
      </View>
    );
  }

  if (!data) return null;

  const pillars: SciencePillar[] = ['load', 'recovery', 'prediction', 'zones'];

  return (
    <View className={`sci-root ${themeClassName()}`}>
      <Text className="sci-intro">
        Praxys's numbers come from published research. These are the
        theories currently powering your dashboard, plus the alternatives
        you could switch to on the web.
      </Text>

      {pillars.map((pillar) => {
        const active = data.active?.[pillar];
        const alternatives = data.available?.[pillar] ?? [];
        return (
          <Pillar
            key={pillar}
            pillar={pillar}
            active={active}
            alternatives={alternatives}
          />
        );
      })}

      <View className="ts-card">
        <Text className="ts-section-label">Zone labels</Text>
        <Text className="sci-line">
          Currently using: <Text className="ts-value">{data.active_labels}</Text>
        </Text>
        {data.label_sets.length > 1 && (
          <Text className="sci-muted-line ts-muted">
            {data.label_sets.length} label sets available — switch on the web.
          </Text>
        )}
      </View>
    </View>
  );
}

function Pillar({
  pillar,
  active,
  alternatives,
}: {
  pillar: SciencePillar;
  active: TheorySummary | undefined;
  alternatives: TheorySummary[];
}) {
  return (
    <View className="ts-card">
      <Text className="ts-section-label">{PILLAR_LABELS[pillar]}</Text>
      <Text className="sci-pillar-desc ts-muted">{PILLAR_DESCRIPTIONS[pillar]}</Text>

      {active ? (
        <View className="sci-active">
          <Text className="sci-active-label ts-primary">CURRENT</Text>
          <Text className="sci-active-name">{active.name}</Text>
          <Text className="sci-active-author ts-muted">{active.author}</Text>
          <Text className="sci-active-desc">{active.simple_description}</Text>
        </View>
      ) : (
        <Text className="ts-muted">No active theory configured.</Text>
      )}

      {alternatives.length > 1 && (
        <View className="sci-alt-section">
          <Text className="sci-alt-label ts-muted">
            Alternatives ({alternatives.length - 1})
          </Text>
          {alternatives
            .filter((a) => a.id !== active?.id)
            .slice(0, 5)
            .map((alt) => (
              <View key={alt.id} className="sci-alt-row">
                <Text className="sci-alt-name">{alt.name}</Text>
                <Text className="sci-alt-author ts-muted">{alt.author}</Text>
                <Text className="sci-alt-desc">{alt.simple_description}</Text>
              </View>
            ))}
        </View>
      )}
    </View>
  );
}
