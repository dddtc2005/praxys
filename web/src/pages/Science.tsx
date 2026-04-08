import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useScience } from '../contexts/ScienceContext';
import type { SciencePillar, TheorySummary } from '../types/api';

/* ── Per-pillar identity ──────────────────────────────────────────────── */

const PILLARS: {
  key: SciencePillar;
  num: string;
  label: string;
  question: string;
  accent: string;
}[] = [
  { key: 'load', num: '01', label: 'Load & Fitness', question: 'How does training stress become fitness?', accent: '#00ff87' },
  { key: 'recovery', num: '02', label: 'Recovery', question: 'How do we know if you\'re ready to train hard?', accent: '#a78bfa' },
  { key: 'prediction', num: '03', label: 'Race Prediction', question: 'How do we estimate your race potential?', accent: '#f59e0b' },
  { key: 'zones', num: '04', label: 'Training Zones', question: 'How is intensity classified?', accent: '#3b82f6' },
];

/* ── Pillar Section ───────────────────────────────────────────────────── */

function PillarSection({
  num,
  label,
  question,
  accent,
  pillar,
  active,
  alternatives,
  recommendation,
  onSelect,
}: {
  num: string;
  label: string;
  question: string;
  accent: string;
  pillar: SciencePillar;
  active: TheorySummary | undefined;
  alternatives: TheorySummary[];
  recommendation?: { recommended_id: string; reason: string; confidence: string };
  onSelect: (pillar: SciencePillar, id: string) => void;
}) {
  const [mode, setMode] = useState<'simple' | 'advanced'>('simple');

  if (!active) return null;

  const others = alternatives.filter((t) => t.id !== active.id);

  return (
    <section
      id={pillar}
      className="scroll-mt-8 group"
    >
      {/* ── Pillar header row ── */}
      <div className="flex items-baseline gap-4 mb-5">
        <span
          className="text-4xl font-black font-data opacity-20 select-none leading-none"
          style={{ color: accent }}
        >
          {num}
        </span>
        <div className="flex-1 min-w-0">
          <h2 className="text-lg font-bold text-text-primary tracking-tight">{label}</h2>
          <p className="text-sm text-text-muted mt-0.5">{question}</p>
        </div>
        {/* Simple / Advanced segmented control */}
        <div
          className="flex rounded-full p-0.5 shrink-0"
          style={{ backgroundColor: `${accent}10`, border: `1px solid ${accent}25` }}
        >
          <button
            onClick={() => setMode('simple')}
            className="rounded-full px-4 py-1.5 text-xs font-semibold transition-all duration-200"
            style={
              mode === 'simple'
                ? { backgroundColor: accent, color: '#0a0a0f' }
                : { color: `${accent}99` }
            }
          >
            Simple
          </button>
          <button
            onClick={() => setMode('advanced')}
            className="rounded-full px-4 py-1.5 text-xs font-semibold transition-all duration-200"
            style={
              mode === 'advanced'
                ? { backgroundColor: accent, color: '#0a0a0f' }
                : { color: `${accent}99` }
            }
          >
            Advanced
          </button>
        </div>
      </div>

      {/* ── Active theory card ── */}
      <div
        className="rounded-2xl overflow-hidden transition-all duration-300"
        style={{
          borderLeft: `3px solid ${accent}`,
          boxShadow: `inset 3px 0 12px -4px ${accent}20, 0 1px 3px rgba(0,0,0,0.2)`,
          backgroundColor: 'var(--color-panel)',
        }}
      >
        {/* Active header */}
        <div className="px-6 pt-5 pb-3 flex items-center gap-3">
          <span
            className="h-2.5 w-2.5 rounded-full animate-pulse"
            style={{ backgroundColor: accent }}
          />
          <span className="text-xs font-bold uppercase tracking-widest" style={{ color: accent }}>
            Active
          </span>
          <span className="text-sm font-semibold text-text-primary">{active.name}</span>
        </div>

        {/* Content area */}
        <div className="px-6 pb-6">
          <div
            className="transition-all duration-300 overflow-hidden"
            style={{ maxHeight: mode === 'advanced' ? '2000px' : '500px' }}
          >
            {mode === 'simple' ? (
              <p className="text-[15px] text-text-secondary leading-[1.7] max-w-prose">
                {active.simple_description || active.description}
              </p>
            ) : (
              <div className="space-y-4">
                <div
                  className="science-markdown rounded-xl p-5 text-[13px] leading-[1.8]"
                  style={{
                    backgroundColor: `${accent}08`,
                    border: `1px solid ${accent}15`,
                    color: 'var(--color-text-secondary)',
                    ['--md-accent' as string]: accent,
                  }}
                >
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {active.advanced_description || active.description}
                  </ReactMarkdown>
                </div>

                {/* Citations */}
                {active.citations?.length > 0 && (
                  <div className="pl-4" style={{ borderLeft: `2px solid ${accent}30` }}>
                    <p
                      className="text-[10px] font-bold uppercase tracking-widest mb-2"
                      style={{ color: `${accent}80` }}
                    >
                      References
                    </p>
                    <ol className="space-y-1.5 list-decimal list-inside">
                      {active.citations.map((c: any, i: number) => (
                        <li key={i} className="text-xs text-text-muted leading-relaxed">
                          {c.authors && (
                            <span className="text-text-secondary">{c.authors}. </span>
                          )}
                          <span className="italic">{c.title}</span>
                          {c.year && ` (${c.year})`}
                          {c.journal && `. ${c.journal}`}
                          {c.url && (
                            <a
                              href={c.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="ml-1.5 underline decoration-dotted underline-offset-2 hover:text-text-secondary"
                              style={{ color: `${accent}90` }}
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
            )}
          </div>
        </div>
      </div>

      {/* ── Recommendation ── */}
      {recommendation && recommendation.recommended_id !== active.id && (
        <div
          className="mt-3 rounded-xl px-5 py-3.5 flex items-start gap-3"
          style={{
            backgroundColor: '#f59e0b08',
            border: '1px solid #f59e0b25',
          }}
        >
          <span className="h-2 w-2 rounded-full bg-accent-amber mt-1.5 shrink-0 animate-pulse" />
          <div>
            <p className="text-xs font-semibold text-accent-amber">
              Based on your training, we suggest:{' '}
              {alternatives.find((t) => t.id === recommendation.recommended_id)?.name}
            </p>
            <p className="text-xs text-text-muted mt-0.5">{recommendation.reason}</p>
          </div>
        </div>
      )}

      {/* ── Alternative theories ── */}
      {others.length > 0 && (
        <div className="mt-4 space-y-2">
          {others.map((theory) => (
            <div
              key={theory.id}
              className="rounded-xl border border-border bg-panel/50 px-5 py-4 transition-colors hover:border-border/80"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-text-primary">{theory.name}</p>
                  <p className="text-xs text-text-muted mt-1 leading-relaxed max-w-prose">
                    {mode === 'simple'
                      ? theory.simple_description || theory.description
                      : theory.advanced_description || theory.description}
                  </p>
                </div>
                <button
                  onClick={() => onSelect(pillar, theory.id)}
                  className="shrink-0 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all duration-200 border"
                  style={{
                    borderColor: `${accent}40`,
                    color: accent,
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = `${accent}15`;
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = 'transparent';
                  }}
                >
                  Use this
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/* ── Main Page ────────────────────────────────────────────────────────── */

export default function Science() {
  const { science, loading, updateScience } = useScience();

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="h-10 w-10 rounded-full border-4 border-border border-t-accent-green animate-spin" />
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

  const handleSelect = (pillar: SciencePillar, theoryId: string) => {
    updateScience({ science: { [pillar]: theoryId } });
  };

  const handleLabels = (labelId: string) => {
    updateScience({ zone_labels: labelId });
  };

  return (
    <div>
      {/* ── Hero header ── */}
      <div
        className="relative rounded-2xl overflow-hidden mb-10 px-8 py-10"
        style={{
          background: 'linear-gradient(135deg, #0a0a0f 0%, #111827 50%, #0f1724 100%)',
          boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.03)',
        }}
      >
        {/* Decorative mesh dots */}
        <div
          className="absolute inset-0 opacity-[0.03]"
          style={{
            backgroundImage: 'radial-gradient(circle, #fff 1px, transparent 1px)',
            backgroundSize: '24px 24px',
          }}
        />
        <div className="relative">
          <p className="text-xs font-bold uppercase tracking-[0.3em] text-text-muted mb-3">
            Training Science
          </p>
          <h1 className="text-3xl font-black text-text-primary tracking-tight leading-tight">
            The science behind<br />
            <span className="bg-gradient-to-r from-[#00ff87] via-[#a78bfa] to-[#3b82f6] bg-clip-text text-transparent">
              your analysis
            </span>
          </h1>
          <p className="text-sm text-text-muted mt-4 max-w-lg leading-relaxed">
            Four scientific pillars power your training dashboard. Each uses a published theory
            you can understand, verify, and change. We suggest the best fit based on your data.
          </p>
        </div>

        {/* Pillar quick-nav */}
        <div className="relative flex gap-2 mt-6">
          {PILLARS.map((p) => (
            <a
              key={p.key}
              href={`#${p.key}`}
              className="rounded-lg px-3 py-1.5 text-xs font-semibold transition-all duration-200 hover:scale-105"
              style={{
                backgroundColor: `${p.accent}12`,
                color: p.accent,
                border: `1px solid ${p.accent}20`,
              }}
            >
              {p.label}
            </a>
          ))}
        </div>
      </div>

      {/* ── Pillar sections ── */}
      <div className="space-y-12">
        {PILLARS.map((p) => (
          <PillarSection
            key={p.key}
            num={p.num}
            label={p.label}
            question={p.question}
            accent={p.accent}
            pillar={p.key}
            active={science.active[p.key]}
            alternatives={science.available[p.key] ?? []}
            recommendation={recs.find((r) => r.pillar === p.key)}
            onSelect={handleSelect}
          />
        ))}
      </div>

      {/* ── Zone labels ── */}
      <div
        className="mt-12 rounded-2xl border border-border bg-panel px-6 py-5"
      >
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-text-primary">Zone Labels</p>
            <p className="text-xs text-text-muted mt-0.5">
              Cosmetic only — changes zone names and colors without affecting calculations
            </p>
          </div>
          <div className="flex rounded-full overflow-hidden border border-border shrink-0">
            {(science.label_sets ?? []).map((ls) => {
              const isActive = science.active_labels === ls.id;
              return (
                <button
                  key={ls.id}
                  onClick={() => handleLabels(ls.id)}
                  className={`px-4 py-1.5 text-xs font-semibold transition-all duration-200 ${
                    isActive
                      ? 'bg-accent-green/15 text-accent-green'
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
