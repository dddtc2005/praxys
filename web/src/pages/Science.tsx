import { useState } from 'react';
import { useScience } from '../contexts/ScienceContext';
import type { SciencePillar, TheorySummary } from '../types/api';

const PILLAR_META: Record<string, { label: string; icon: string; question: string }> = {
  load: {
    label: 'Load & Fitness',
    icon: '\u26a1',
    question: 'How does training stress become fitness?',
  },
  recovery: {
    label: 'Recovery',
    icon: '\ud83d\udca4',
    question: 'How do we know if you\'re ready to train hard?',
  },
  prediction: {
    label: 'Race Prediction',
    icon: '\ud83c\udfc1',
    question: 'How do we estimate your race potential?',
  },
  zones: {
    label: 'Training Zones',
    icon: '\ud83c\udfaf',
    question: 'How is intensity classified?',
  },
};

function PillarCard({
  pillar,
  active,
  alternatives,
  recommendation,
  onSelectTheory,
}: {
  pillar: SciencePillar;
  active: TheorySummary | undefined;
  alternatives: TheorySummary[];
  recommendation?: { recommended_id: string; reason: string; confidence: string };
  onSelectTheory: (pillar: SciencePillar, theoryId: string) => void;
}) {
  const [mode, setMode] = useState<'simple' | 'advanced'>('simple');
  const meta = PILLAR_META[pillar];

  if (!active) return null;

  const otherTheories = alternatives.filter((t) => t.id !== active.id);

  return (
    <div id={pillar} className="rounded-2xl bg-panel overflow-hidden scroll-mt-6">
      {/* Header */}
      <div className="p-5 sm:p-6 pb-0">
        <div className="flex items-start justify-between gap-4 mb-3">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-lg">{meta.icon}</span>
              <h2 className="text-base font-semibold text-text-primary">{meta.label}</h2>
            </div>
            <p className="text-sm text-text-secondary">{meta.question}</p>
          </div>

          {/* Simple / Advanced toggle */}
          <div className="flex rounded-lg border border-border overflow-hidden shrink-0">
            <button
              onClick={() => setMode('simple')}
              className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                mode === 'simple'
                  ? 'bg-accent-green/15 text-accent-green'
                  : 'bg-panel-light text-text-muted hover:text-text-secondary'
              }`}
            >
              Simple
            </button>
            <button
              onClick={() => setMode('advanced')}
              className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                mode === 'advanced'
                  ? 'bg-accent-green/15 text-accent-green'
                  : 'bg-panel-light text-text-muted hover:text-text-secondary'
              }`}
            >
              Advanced
            </button>
          </div>
        </div>

        {/* Theory selector */}
        <div className="flex items-center gap-2 mb-4">
          <div className="flex rounded-lg border border-border overflow-hidden">
            {alternatives.map((theory) => {
              const isSelected = active.id === theory.id;
              const isRecommended = recommendation?.recommended_id === theory.id;
              return (
                <button
                  key={theory.id}
                  onClick={() => onSelectTheory(pillar, theory.id)}
                  className={`px-3 py-1.5 text-xs font-medium transition-colors relative ${
                    isSelected
                      ? 'bg-accent-green/15 text-accent-green'
                      : 'bg-panel-light text-text-muted hover:text-text-secondary'
                  }`}
                >
                  {theory.name}
                  {isRecommended && !isSelected && (
                    <span className="absolute -top-0.5 -right-0.5 h-1.5 w-1.5 rounded-full bg-accent-amber" />
                  )}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="px-5 sm:px-6 pb-5 sm:pb-6">
        {mode === 'simple' ? (
          <div className="rounded-xl bg-panel-light p-4">
            <p className="text-sm text-text-secondary leading-relaxed">
              {active.simple_description || active.description}
            </p>
          </div>
        ) : (
          <div className="rounded-xl bg-panel-light p-4 space-y-3">
            <div className="text-sm text-text-secondary leading-relaxed whitespace-pre-line font-data text-[13px]">
              {active.advanced_description || active.description}
            </div>

            {/* Citations */}
            {active.citations?.length > 0 && (
              <div className="pt-3 border-t border-border">
                <p className="text-[10px] text-text-muted uppercase tracking-wider mb-2">Sources</p>
                <div className="space-y-1">
                  {active.citations.map((c: any, i: number) => (
                    <p key={i} className="text-xs text-text-muted">
                      {c.authors && <span className="text-text-secondary">{c.authors}. </span>}
                      {c.title}
                      {c.year && ` (${c.year})`}
                      {c.journal && <span className="italic">. {c.journal}</span>}
                      {c.url && (
                        <>
                          {' '}
                          <a
                            href={c.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="underline hover:text-text-secondary"
                          >
                            Link
                          </a>
                        </>
                      )}
                    </p>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Recommendation */}
        {recommendation && recommendation.recommended_id !== active.id && (
          <div className="mt-3 rounded-xl bg-accent-amber/5 border border-accent-amber/20 px-4 py-3">
            <p className="text-xs font-medium text-accent-amber">
              Based on your training, we suggest:{' '}
              {alternatives.find((t) => t.id === recommendation.recommended_id)?.name}
            </p>
            <p className="text-xs text-text-muted mt-0.5">{recommendation.reason}</p>
          </div>
        )}

        {/* Other available theories (brief) */}
        {otherTheories.length > 0 && (
          <div className="mt-4">
            <p className="text-[10px] text-text-muted uppercase tracking-wider mb-2">Other options</p>
            <div className="space-y-2">
              {otherTheories.map((theory) => (
                <button
                  key={theory.id}
                  onClick={() => onSelectTheory(pillar, theory.id)}
                  className="w-full rounded-lg bg-base/50 border border-border px-4 py-3 text-left hover:border-accent-green/30 transition-colors"
                >
                  <p className="text-sm font-medium text-text-primary">{theory.name}</p>
                  <p className="text-xs text-text-muted mt-0.5">
                    {mode === 'simple'
                      ? theory.simple_description || theory.description
                      : theory.advanced_description || theory.description}
                  </p>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function Science() {
  const { science, loading, updateScience } = useScience();

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent-green border-t-transparent" />
      </div>
    );
  }

  if (!science) {
    return (
      <div className="rounded-2xl bg-panel p-6 text-center">
        <p className="text-accent-red font-semibold mb-2">Failed to load science data</p>
      </div>
    );
  }

  const recs = science.recommendations ?? [];

  const handleSelectTheory = (pillar: SciencePillar, theoryId: string) => {
    updateScience({ science: { [pillar]: theoryId } });
  };

  const handleLabelsChange = (labelId: string) => {
    updateScience({ zone_labels: labelId });
  };

  return (
    <div>
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-text-primary">Training Science</h1>
        <p className="text-sm text-text-secondary mt-1">How your analysis works</p>
      </div>

      {/* Intro */}
      <div className="rounded-2xl bg-panel p-5 sm:p-6 mb-6">
        <p className="text-sm text-text-secondary leading-relaxed">
          Your training analysis is built on four scientific pillars. Each pillar uses a specific
          theory to answer a key question about your training. Select the theory that best matches
          your training style — we'll suggest the best fit based on your data.
        </p>
      </div>

      {/* Pillar cards */}
      <div className="space-y-6">
        {(['load', 'recovery', 'prediction', 'zones'] as SciencePillar[]).map((pillar) => (
          <PillarCard
            key={pillar}
            pillar={pillar}
            active={science.active[pillar]}
            alternatives={science.available[pillar] ?? []}
            recommendation={recs.find((r) => r.pillar === pillar)}
            onSelectTheory={handleSelectTheory}
          />
        ))}
      </div>

      {/* Zone labels preference */}
      <div className="rounded-2xl bg-panel p-5 sm:p-6 mt-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-text-primary">Zone Labels</p>
            <p className="text-xs text-text-muted mt-0.5">Changes zone names and colors without affecting calculations</p>
          </div>
          <div className="flex rounded-lg border border-border overflow-hidden shrink-0">
            {(science.label_sets ?? []).map((ls) => {
              const isSelected = science.active_labels === ls.id;
              return (
                <button
                  key={ls.id}
                  onClick={() => handleLabelsChange(ls.id)}
                  className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                    isSelected
                      ? 'bg-accent-green/15 text-accent-green'
                      : 'bg-panel-light text-text-muted hover:text-text-secondary'
                  }`}
                >
                  {ls.name}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
