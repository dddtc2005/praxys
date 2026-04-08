import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useScience } from '../contexts/ScienceContext';
import type { SciencePillar, TheorySummary } from '../types/api';

/* ── Pillar config ────────────────────────────────────────────────────── */

const PILLARS: {
  key: SciencePillar;
  label: string;
  question: string;
  accent: string;
}[] = [
  { key: 'load', label: 'Load & Fitness', question: 'How does training stress become fitness?', accent: '#00ff87' },
  { key: 'recovery', label: 'Recovery', question: 'How do we assess readiness to train?', accent: '#a78bfa' },
  { key: 'prediction', label: 'Race Prediction', question: 'How do we estimate race potential?', accent: '#f59e0b' },
  { key: 'zones', label: 'Training Zones', question: 'How is intensity classified?', accent: '#3b82f6' },
];

/* ── Markdown wrapper ─────────────────────────────────────────────────── */

function Md({ children, accent }: { children: string; accent: string }) {
  return (
    <div className="science-markdown" style={{ ['--md-accent' as string]: accent }}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}

/* ── Theory card (used for both active and alternative) ───────────────── */

function TheoryContent({
  theory,
  mode,
  accent,
}: {
  theory: TheorySummary;
  mode: 'simple' | 'advanced';
  accent: string;
}) {
  if (mode === 'simple') {
    return (
      <p className="text-sm text-text-secondary leading-[1.75]">
        {theory.simple_description || theory.description}
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <Md accent={accent}>{theory.advanced_description || theory.description}</Md>

      {theory.citations?.length > 0 && (
        <div className="pt-3 border-t border-border/50">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-text-muted mb-2">
            References
          </p>
          <ol className="space-y-1 list-decimal list-inside text-xs text-text-muted">
            {theory.citations.map((c: any, i: number) => (
              <li key={i} className="leading-relaxed">
                {c.authors && <span className="text-text-secondary">{c.authors}. </span>}
                <span className="italic">{c.title}</span>
                {c.year && ` (${c.year})`}
                {c.journal && `. ${c.journal}`}
                {c.url && (
                  <a
                    href={c.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="ml-1 underline decoration-dotted underline-offset-2 hover:text-text-secondary transition-colors"
                  >
                    view
                  </a>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

/* ── Pillar section ───────────────────────────────────────────────────── */

function PillarSection({
  pillar,
  label,
  question,
  accent,
  active,
  alternatives,
  recommendation,
  onSelect,
}: {
  pillar: SciencePillar;
  label: string;
  question: string;
  accent: string;
  active: TheorySummary | undefined;
  alternatives: TheorySummary[];
  recommendation?: { recommended_id: string; reason: string; confidence: string };
  onSelect: (pillar: SciencePillar, id: string) => void;
}) {
  const [mode, setMode] = useState<'simple' | 'advanced'>('simple');

  if (!active) return null;

  const others = alternatives.filter((t) => t.id !== active.id);

  return (
    <section id={pillar} className="scroll-mt-8">
      {/* Header */}
      <div className="flex items-end justify-between gap-4 mb-4">
        <div>
          <h2 className="text-xl font-bold text-text-primary tracking-tight">{label}</h2>
          <p className="text-sm text-text-muted">{question}</p>
        </div>
        <div className="flex gap-1 shrink-0">
          {(['simple', 'advanced'] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                mode === m
                  ? 'bg-panel-light text-text-primary'
                  : 'text-text-muted hover:text-text-secondary'
              }`}
            >
              {m === 'simple' ? 'Simple' : 'Advanced'}
            </button>
          ))}
        </div>
      </div>

      {/* Active theory */}
      <div
        className="rounded-xl p-5 sm:p-6"
        style={{
          backgroundColor: 'var(--color-panel)',
          borderLeft: `2px solid ${accent}`,
        }}
      >
        <div className="flex items-center gap-2 mb-3">
          <span className="text-xs font-semibold tracking-wide" style={{ color: accent }}>
            {active.name}
          </span>
          <span className="text-[10px] text-text-muted">&mdash; active</span>
        </div>

        <TheoryContent theory={active} mode={mode} accent={accent} />
      </div>

      {/* Recommendation */}
      {recommendation && recommendation.recommended_id !== active.id && (
        <p className="text-xs text-accent-amber mt-3 px-1">
          Based on your training, we suggest{' '}
          <span className="font-semibold">
            {alternatives.find((t) => t.id === recommendation.recommended_id)?.name}
          </span>
          {' '}&mdash; {recommendation.reason}
        </p>
      )}

      {/* Alternatives */}
      {others.map((theory) => (
        <div
          key={theory.id}
          className="mt-3 rounded-xl border border-border/50 p-5 sm:p-6"
          style={{ backgroundColor: 'var(--color-panel)' }}
        >
          <div className="flex items-start justify-between gap-4 mb-3">
            <span className="text-xs font-semibold text-text-secondary tracking-wide">
              {theory.name}
            </span>
            <button
              onClick={() => onSelect(pillar, theory.id)}
              className="shrink-0 text-xs font-medium px-3 py-1 rounded-md transition-colors border border-border hover:border-text-muted text-text-muted hover:text-text-primary"
            >
              Use this
            </button>
          </div>

          <TheoryContent theory={theory} mode={mode} accent={accent} />
        </div>
      ))}
    </section>
  );
}

/* ── Page ──────────────────────────────────────────────────────────────── */

export default function Science() {
  const { science, loading, updateScience } = useScience();

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="h-8 w-8 rounded-full border-2 border-border border-t-accent-green animate-spin" />
      </div>
    );
  }

  if (!science) {
    return (
      <div className="rounded-2xl bg-panel p-6 text-center">
        <p className="text-accent-red font-semibold">Failed to load science data</p>
      </div>
    );
  }

  const recs = science.recommendations ?? [];

  return (
    <div>
      {/* Header */}
      <div className="mb-10">
        <h1 className="text-2xl font-bold text-text-primary">Training Science</h1>
        <p className="text-sm text-text-muted mt-1 max-w-lg">
          Four pillars power your analysis. Each uses a published theory you can
          understand, verify, and change.
        </p>
      </div>

      {/* Pillars */}
      <div className="space-y-14">
        {PILLARS.map((p) => (
          <PillarSection
            key={p.key}
            pillar={p.key}
            label={p.label}
            question={p.question}
            accent={p.accent}
            active={science.active[p.key]}
            alternatives={science.available[p.key] ?? []}
            recommendation={recs.find((r) => r.pillar === p.key)}
            onSelect={(pillar, id) => updateScience({ science: { [pillar]: id } })}
          />
        ))}
      </div>

      {/* Zone labels */}
      <div className="mt-14 pt-6 border-t border-border/30">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-text-primary">Zone Labels</p>
            <p className="text-xs text-text-muted mt-0.5">
              Cosmetic &mdash; changes names and colors without affecting calculations
            </p>
          </div>
          <div className="flex gap-1">
            {(science.label_sets ?? []).map((ls) => {
              const isActive = science.active_labels === ls.id;
              return (
                <button
                  key={ls.id}
                  onClick={() => updateScience({ zone_labels: ls.id })}
                  className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                    isActive
                      ? 'bg-panel-light text-text-primary'
                      : 'text-text-muted hover:text-text-secondary'
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
