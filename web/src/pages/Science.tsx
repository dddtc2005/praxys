import { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useAuth } from '@/hooks/useAuth';
import { useScience } from '@/contexts/ScienceContext';
import type { SciencePillar, TheorySummary, PillarRecommendation, ScienceResponse } from '@/types/api';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Trans, useLingui } from '@lingui/react/macro';
import { msg } from '@lingui/core/macro';
import type { I18n, MessageDescriptor } from '@lingui/core';
import { cn } from '@/lib/utils';

/* ── Pillar metadata ──────────────────────────────────────────────────── */

interface PillarMeta {
  key: SciencePillar;
  num: string;
  label: MessageDescriptor;
  question: MessageDescriptor;
}

const PILLARS: PillarMeta[] = [
  { key: 'load',       num: '01', label: msg`Load & Fitness`,   question: msg`Translates training stress into fitness.` },
  { key: 'recovery',   num: '02', label: msg`Recovery`,         question: msg`Reads readiness from the body's signals.` },
  { key: 'prediction', num: '03', label: msg`Race Prediction`, question: msg`Estimates race performance from current fitness.` },
  { key: 'zones',      num: '04', label: msg`Training Zones`,  question: msg`Defines what counts as easy, threshold, hard.` },
];

const PILLAR_KEYS = PILLARS.map((p) => p.key);

/** Theory `advanced_description` markdown ends with a bold References
 * heading (`**References:**` in EN YAML, `**参考文献：**` in ZH — note
 * the full-width colon) followed by a bulleted list to end of string.
 * That duplicates the structured `citations[]` we render below the
 * markdown, so strip it before render. The structured list is the
 * canonical source — it carries journal names and clickable URLs the
 * markdown bullets don't. */
function stripReferencesBlock(md: string): string {
  return md.replace(/\n+\s*\*\*(?:References|参考文献)[:：]?\*\*[\s\S]*$/i, '').trimEnd();
}

function isPillarKey(s: string): s is SciencePillar {
  return (PILLAR_KEYS as string[]).includes(s);
}

/* ── Page ──────────────────────────────────────────────────────────────── */

export default function Science() {
  const { isDemo } = useAuth();
  const { science, loading, updateScience } = useScience();
  const { i18n } = useLingui();

  const [focused, setFocused] = useState<SciencePillar>(() => {
    if (typeof window === 'undefined') return 'load';
    const hash = window.location.hash.replace('#', '');
    return isPillarKey(hash) ? hash : 'load';
  });
  const [previewing, setPreviewing] = useState<Partial<Record<SciencePillar, string>>>({});
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    const onHash = () => {
      const hash = window.location.hash.replace('#', '');
      if (isPillarKey(hash)) setFocused(hash);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const selectPillar = (p: SciencePillar) => {
    if (p === focused) return;
    setFocused(p);
    setShowAdvanced(false);
    window.history.replaceState(null, '', `#${p}`);
  };

  if (loading) return <ScienceSkeleton />;
  if (!science) {
    return (
      <p className="py-12 text-sm text-destructive">
        <Trans>Failed to load science data.</Trans>
      </p>
    );
  }

  const meta = PILLARS.find((p) => p.key === focused)!;
  const active = science.active[focused];
  const alternatives = science.available[focused] ?? [];
  const recommendation = science.recommendations.find((r) => r.pillar === focused);
  const previewId = previewing[focused];
  const isPreviewMode = Boolean(previewId && previewId !== active?.id);
  const shownTheory: TheorySummary | undefined =
    isPreviewMode ? alternatives.find((t) => t.id === previewId) : active;

  const handleChicletClick = (id: string) => {
    if (id === active?.id) {
      // Re-activating active chiclet cancels any preview.
      setPreviewing((p) => ({ ...p, [focused]: undefined }));
    } else {
      setPreviewing((p) => ({ ...p, [focused]: id }));
    }
    setShowAdvanced(false);
  };

  const handleSwitch = () => {
    if (!previewId || isDemo) return;
    updateScience({ science: { [focused]: previewId } });
    setPreviewing((p) => ({ ...p, [focused]: undefined }));
  };

  const handleCancelPreview = () => {
    setPreviewing((p) => ({ ...p, [focused]: undefined }));
  };

  return (
    <div className="science-page">
      <PageHeader
        science={science}
        isDemo={isDemo}
        onLabelChange={(id) => updateScience({ zone_labels: id })}
      />

      <div className="grid gap-6 lg:grid-cols-[260px_1fr] lg:gap-12">
        <PillarRail
          focused={focused}
          onSelect={selectPillar}
          science={science}
          i18n={i18n}
        />

        <PillarDetail
          meta={meta}
          active={active}
          shown={shownTheory}
          alternatives={alternatives}
          recommendation={recommendation}
          isPreviewMode={isPreviewMode}
          previewId={previewId}
          showAdvanced={showAdvanced}
          isDemo={isDemo}
          onChiclet={handleChicletClick}
          onSwitch={handleSwitch}
          onCancel={handleCancelPreview}
          onToggleAdvanced={() => setShowAdvanced((s) => !s)}
          i18n={i18n}
        />
      </div>
    </div>
  );
}

/* ── Page header ──────────────────────────────────────────────────────── */

function PageHeader({
  science,
  isDemo,
  onLabelChange,
}: {
  science: ScienceResponse;
  isDemo: boolean;
  onLabelChange: (id: string) => void;
}) {
  const labelSets = science.label_sets ?? [];
  return (
    <header className="mb-10 flex flex-col gap-6 lg:mb-14 lg:flex-row lg:items-end lg:justify-between">
      <div>
        <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground mb-2">
          <Trans>Four-pillar framework</Trans>
        </p>
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">
          <Trans>Training Science</Trans>
        </h1>
        <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
          <Trans>
            Each pillar runs a published theory you can read, verify, and swap.
            Praxys interprets your data through whichever framework you choose.
          </Trans>
        </p>
      </div>

      {labelSets.length > 0 && (
        <div className="flex items-center gap-3">
          <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground whitespace-nowrap">
            <Trans>Zone labels</Trans>
          </span>
          <ToggleGroup
            value={[science.active_labels]}
            onValueChange={(v) => {
              if (v.length && !isDemo) onLabelChange(v[v.length - 1]);
            }}
            spacing={4}
          >
            {labelSets.map((ls) => (
              <ToggleGroupItem key={ls.id} value={ls.id} size="sm" disabled={isDemo}>
                {ls.name}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </div>
      )}
    </header>
  );
}

/* ── Pillar rail (left on desktop, top strip on mobile) ───────────────── */

function PillarRail({
  focused,
  onSelect,
  science,
  i18n,
}: {
  focused: SciencePillar;
  onSelect: (p: SciencePillar) => void;
  science: ScienceResponse;
  i18n: I18n;
}) {
  const recAvailableAria = i18n._(msg`Recommendation available`);
  return (
    <nav
      aria-label={i18n._(msg`Science pillars`)}
      className={cn(
        '-mx-4 flex gap-2 overflow-x-auto px-4 pb-3 border-b border-border',
        // Desktop: vertical rail with right border.
        'lg:mx-0 lg:px-0 lg:pb-0 lg:border-b-0 lg:flex-col lg:gap-0 lg:overflow-visible lg:border-r lg:pr-6 lg:sticky lg:top-6 lg:self-start',
      )}
    >
      {PILLARS.map((p) => {
        const active = science.active[p.key];
        const rec = science.recommendations.find((r) => r.pillar === p.key);
        const recAvailable = Boolean(rec && rec.recommended_id !== active?.id);
        return (
          <PillarRailItem
            key={p.key}
            num={p.num}
            label={i18n._(p.label)}
            theoryName={active?.name}
            recAvailable={recAvailable}
            recAvailableAria={recAvailableAria}
            isFocused={p.key === focused}
            onClick={() => onSelect(p.key)}
          />
        );
      })}
    </nav>
  );
}

function PillarRailItem({
  num,
  label,
  theoryName,
  recAvailable,
  recAvailableAria,
  isFocused,
  onClick,
}: {
  num: string;
  label: string;
  theoryName?: string;
  recAvailable: boolean;
  recAvailableAria: string;
  isFocused: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={isFocused ? 'true' : undefined}
      className={cn(
        // Common
        'group/rail-item relative shrink-0 text-left transition-colors duration-150 outline-none',
        // Mobile: pill chip
        'rounded-md border px-3 py-2 min-w-[160px]',
        isFocused
          ? 'border-foreground/30 bg-secondary'
          : 'border-transparent bg-transparent hover:bg-secondary/60',
        // Desktop: full-width row, no chip border, left edge indicator instead
        'lg:rounded-none lg:border-0 lg:border-l-2 lg:border-l-transparent lg:bg-transparent lg:px-4 lg:py-3 lg:min-w-0',
        'lg:hover:bg-secondary/40',
        isFocused && 'lg:border-l-[var(--accent-cobalt-val)] lg:bg-secondary/60',
        'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
      )}
    >
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-[10px] tracking-wider text-muted-foreground font-data">
          {num}
        </span>
        <span
          className={cn(
            'text-sm font-medium tracking-tight',
            isFocused ? 'text-foreground' : 'text-foreground/80',
          )}
        >
          {label}
        </span>
        {recAvailable && (
          <span
            aria-label={recAvailableAria}
            className="ml-auto inline-block size-1.5 rounded-full bg-[var(--accent-amber-val)]"
          />
        )}
      </div>
      {theoryName && (
        <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground font-data">
          {theoryName}
        </div>
      )}
    </button>
  );
}

/* ── Pillar detail ────────────────────────────────────────────────────── */

function PillarDetail({
  meta,
  active,
  shown,
  alternatives,
  recommendation,
  isPreviewMode,
  previewId,
  showAdvanced,
  isDemo,
  onChiclet,
  onSwitch,
  onCancel,
  onToggleAdvanced,
  i18n,
}: {
  meta: PillarMeta;
  active: TheorySummary | undefined;
  shown: TheorySummary | undefined;
  alternatives: TheorySummary[];
  recommendation: PillarRecommendation | undefined;
  isPreviewMode: boolean;
  previewId: string | undefined;
  showAdvanced: boolean;
  isDemo: boolean;
  onChiclet: (id: string) => void;
  onSwitch: () => void;
  onCancel: () => void;
  onToggleAdvanced: () => void;
  i18n: I18n;
}) {
  if (!active || !shown) return null;

  const previewedTheory = previewId ? alternatives.find((t) => t.id === previewId) : undefined;
  const recommendedDifferent = recommendation && recommendation.recommended_id !== active.id;
  const recommendedTheory = recommendedDifferent
    ? alternatives.find((t) => t.id === recommendation!.recommended_id)
    : undefined;

  return (
    <article className="min-w-0">
      <div className="mb-7">
        <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
          <span className="font-data">{meta.num}</span>
          <span className="mx-2 text-foreground/30">·</span>
          {i18n._(meta.label)}
        </p>
        <h2 className="mt-2 text-2xl font-semibold tracking-tight text-foreground">
          {i18n._(meta.question)}
        </h2>
      </div>

      <div className="mb-6 flex flex-wrap gap-2">
        {alternatives.map((t) => (
          <Chiclet
            key={t.id}
            theory={t}
            isActive={t.id === active.id}
            isPreviewing={t.id === previewId && previewId !== active.id}
            isRecommended={Boolean(recommendation && recommendation.recommended_id === t.id) && t.id !== active.id}
            onClick={() => onChiclet(t.id)}
          />
        ))}
      </div>

      {/* Hide the rec hint once the user starts previewing the recommended theory — the
       * chiclet's amber halo plus the body's "Previewing" tag carry the message; a third
       * surface would double-emphasize and crowd the staged Switch CTA below. */}
      {recommendedDifferent && recommendedTheory && previewId !== recommendation!.recommended_id && (
        <p className="mb-6 text-xs leading-relaxed text-muted-foreground">
          <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--accent-amber-val)] mr-2">
            <Trans>Recommended</Trans>
          </span>
          <Trans>
            Based on your training, <span className="font-medium text-foreground">{recommendedTheory.name}</span> may fit better — {recommendation!.reason}
          </Trans>
        </p>
      )}

      <div className="space-y-2">
        <div className="flex items-baseline gap-3 text-xs text-muted-foreground">
          {shown.author && shown.author !== 'system' && (
            <span>
              <Trans>by</Trans> <span className="text-foreground/80">{shown.author}</span>
            </span>
          )}
          {!isPreviewMode && (
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--accent-cobalt-val)]">
              <Trans>Active</Trans>
            </span>
          )}
          {isPreviewMode && (
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              <Trans>Previewing</Trans>
            </span>
          )}
        </div>

        <p className="max-w-prose text-[15px] leading-relaxed text-foreground/85">
          {shown.simple_description || shown.description}
        </p>
      </div>

      {isPreviewMode && previewedTheory && (
        <div className="mt-6 flex items-center gap-3">
          <Button
            onClick={onSwitch}
            disabled={isDemo}
            size="sm"
          >
            <Trans>Switch to {previewedTheory.name}</Trans>
          </Button>
          <Button
            onClick={onCancel}
            variant="ghost"
            size="sm"
            className="text-muted-foreground"
          >
            <Trans>Cancel preview</Trans>
          </Button>
          {isDemo && (
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              <Trans>Demo mode — read only</Trans>
            </span>
          )}
        </div>
      )}

      <div className="mt-8 border-t border-border pt-6">
        <button
          type="button"
          onClick={onToggleAdvanced}
          className="group flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.12em] text-[var(--accent-cobalt-val)] transition-colors hover:text-foreground"
          aria-expanded={showAdvanced}
        >
          <span
            aria-hidden
            className={cn(
              'inline-block transition-transform duration-200',
              showAdvanced && 'rotate-90',
            )}
          >
            ›
          </span>
          {showAdvanced ? (
            <Trans>Hide methodology details</Trans>
          ) : (
            <Trans>Show methodology details</Trans>
          )}
        </button>

        {showAdvanced && shown.advanced_description && (
          <div className="mt-5 max-w-prose">
            <div className="science-markdown text-[14px] leading-relaxed text-foreground/85">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {stripReferencesBlock(shown.advanced_description)}
              </ReactMarkdown>
            </div>
          </div>
        )}

        {/* References — always visible inside the disclosure block when present */}
        {showAdvanced && shown.citations?.length > 0 && (
          <div className="mt-8">
            <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground mb-3">
              <Trans>References</Trans>
            </p>
            <ol className="space-y-2 list-decimal list-inside text-xs leading-relaxed text-muted-foreground marker:text-[var(--accent-cobalt-val)]">
              {shown.citations.map((c, i) => {
                const authors = typeof c.authors === 'string' ? c.authors : undefined;
                const title = typeof c.title === 'string' ? c.title : '';
                const year = typeof c.year === 'number' || typeof c.year === 'string' ? c.year : undefined;
                const journal = typeof c.journal === 'string' ? c.journal : undefined;
                const url = typeof c.url === 'string' ? c.url : undefined;
                return (
                  <li key={i}>
                    {authors && <span className="text-foreground/80">{authors}. </span>}
                    <span className="italic">{title}</span>
                    {year !== undefined && <span className="font-data"> ({year})</span>}
                    {journal && <span>. {journal}</span>}
                    {url && (
                      <a
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="ml-1 text-[var(--accent-cobalt-val)] underline decoration-dotted underline-offset-2 hover:opacity-80 transition-opacity"
                      >
                        <Trans>view</Trans>
                      </a>
                    )}
                  </li>
                );
              })}
            </ol>
          </div>
        )}
      </div>
    </article>
  );
}

/* ── Chiclet ──────────────────────────────────────────────────────────── */

function Chiclet({
  theory,
  isActive,
  isPreviewing,
  isRecommended,
  onClick,
}: {
  theory: TheorySummary;
  isActive: boolean;
  isPreviewing: boolean;
  isRecommended: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'group/chiclet relative flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors duration-150 outline-none',
        // Default
        'border-border text-foreground/70 hover:border-foreground/30 hover:text-foreground',
        // Active (current selection)
        isActive && 'border-foreground/40 bg-secondary text-foreground',
        // Previewing (different from active)
        isPreviewing && 'border-[var(--accent-cobalt-val)] text-[var(--accent-cobalt-val)] bg-transparent',
        // Recommendation halo (shown when not active and not previewing)
        isRecommended && !isPreviewing && 'border-[var(--accent-amber-val)]/60 text-foreground',
        'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
      )}
    >
      <span>{theory.name}</span>
      {isActive && (
        <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-[var(--accent-cobalt-val)]">
          ·&nbsp;<Trans>Active</Trans>
        </span>
      )}
      {isPreviewing && (
        <span className="font-mono text-[9px] uppercase tracking-[0.14em]">
          ·&nbsp;<Trans>Previewing</Trans>
        </span>
      )}
      {isRecommended && !isPreviewing && (
        <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-[var(--accent-amber-val)]">
          ·&nbsp;<Trans>Recommended</Trans>
        </span>
      )}
    </button>
  );
}

/* ── Skeleton ─────────────────────────────────────────────────────────── */

function ScienceSkeleton() {
  return (
    <div>
      <div className="mb-10 lg:mb-14">
        <Skeleton className="h-3 w-32 mb-3" />
        <Skeleton className="h-9 w-56" />
        <Skeleton className="h-4 w-80 mt-3" />
      </div>
      <div className="grid gap-6 lg:grid-cols-[260px_1fr] lg:gap-12">
        <div className="flex flex-col gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="space-y-2">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-3 w-24" />
            </div>
          ))}
        </div>
        <div className="space-y-4">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-7 w-3/4" />
          <div className="flex gap-2 pt-2">
            <Skeleton className="h-7 w-32 rounded-full" />
            <Skeleton className="h-7 w-32 rounded-full" />
          </div>
          <Skeleton className="h-32 w-full max-w-prose" />
        </div>
      </div>
    </div>
  );
}
