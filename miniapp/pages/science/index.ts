import type { IAppOption } from '../../app';
import { apiGet, apiPut } from '../../utils/api-client';
import type { ApiError } from '../../utils/api-client';
import type {
  ScienceResponse,
  SciencePillar,
  TheorySummary,
  PillarRecommendation,
} from '../../types/api';
import { applyThemeChrome, themeClassName } from '../../utils/theme';
import { parseMarkdown, copyUrlToClipboard } from '../../utils/markdown';
import { t } from '../../utils/i18n';

function buildScienceTr() {
  return {
    trainingScience: t('Training Science'),
    failedToLoad: t('Failed to load'),
    retry: t('Retry'),
    intro: t(
      "Praxys's numbers come from published research. These are the theories currently powering your dashboard, plus the alternatives you could switch to on the web.",
    ),
    simple: t('Simple'),
    advanced: t('Advanced'),
    active: t('Active'),
    references: t('References'),
    tapToCopy: t('tap to copy URL'),
    zoneLabels: t('Zone labels'),
    currentlyUsing: t('Currently using'),
    suggestion: t('Based on your training, we suggest'),
    noActiveTheory: t('No active theory configured.'),
    useThis: t('Use this'),
    saving: t('Saving…'),
  };
}

function pillarLabels(): Record<SciencePillar, string> {
  return {
    load: t('Load & Fitness'),
    recovery: t('Recovery'),
    prediction: t('Race Prediction'),
    zones: t('Training Zones'),
  };
}

function pillarQuestions(): Record<SciencePillar, string> {
  return {
    load: t('How does training stress become fitness?'),
    recovery: t('How do we assess readiness to train?'),
    prediction: t('How do we estimate race potential?'),
    zones: t('How is intensity classified?'),
  };
}

interface CitationRow {
  display: string;
  url: string;
  hasUrl: boolean;
}

interface TheoryCard {
  id: string;
  name: string;
  author: string;
  simpleText: string;
  advancedHtml: string;
  hasAdvanced: boolean;
  citations: CitationRow[];
  hasCitations: boolean;
}

interface PillarRow {
  pillar: SciencePillar;
  label: string;
  question: string;
  modeIsSimple: boolean;
  modeIsAdvanced: boolean;
  hasActive: boolean;
  activeName: string;
  activeAuthor: string;
  activeCard?: TheoryCard;
  hasRecommendation: boolean;
  recommendationName: string;
  recommendationReason: string;
  hasAlternatives: boolean;
  alternatives: TheoryCard[];
}

interface SciState {
  themeClass: string;
  loading: boolean;
  errorMessage: string;
  hasResponse: boolean;
  pillars: PillarRow[];
  activeLabels: string;
  hasMultipleLabelSets: boolean;
  labelSetCount: number;
  /** Pillar currently mid-save, so the matching button can disable. */
  selectingPillar: SciencePillar | '';
}

const initialData: SciState = {
  themeClass: getApp<IAppOption>().globalData.themeClass,
  loading: true,
  errorMessage: '',
  hasResponse: false,
  pillars: [],
  activeLabels: '',
  hasMultipleLabelSets: false,
  labelSetCount: 0,
  selectingPillar: '',
};

const ALL_PILLARS: SciencePillar[] = ['load', 'recovery', 'prediction', 'zones'];

/**
 * Format a citation object as a readable line. Citations come through
 * the API as `Record<string, unknown>[]` because the YAML schema is
 * loose; we narrow per-field with typeof guards. URLs are surfaced as
 * tappable copy-to-clipboard rows separately because <rich-text> <a>
 * tags don't navigate in mini programs.
 */
function formatCitation(c: Record<string, unknown>): string {
  const parts: string[] = [];
  const authors = typeof c.authors === 'string' ? c.authors : '';
  const title = typeof c.title === 'string' ? c.title : '';
  const year = typeof c.year === 'number' || typeof c.year === 'string' ? c.year : '';
  const journal = typeof c.journal === 'string' ? c.journal : '';

  if (authors) parts.push(`${authors}.`);
  if (title) parts.push(title);
  if (year !== '') parts.push(`(${year})`);
  if (journal) parts.push(journal);

  if (parts.length === 0) {
    const label = typeof c.label === 'string' ? c.label : '';
    if (label) return label;
  }
  return parts.join(' ');
}

function buildTheoryCard(theory: TheorySummary): TheoryCard {
  const advancedSrc = theory.advanced_description || theory.description || '';
  const { html: advancedHtml } = parseMarkdown(advancedSrc);

  const citations: CitationRow[] = (theory.citations ?? []).map((c) => {
    const url = typeof c.url === 'string' ? c.url : '';
    return {
      display: formatCitation(c),
      url,
      hasUrl: !!url,
    };
  });

  return {
    id: theory.id,
    name: theory.name,
    author: theory.author,
    simpleText: theory.simple_description || theory.description || '',
    advancedHtml,
    hasAdvanced: !!advancedHtml,
    citations,
    hasCitations: citations.length > 0,
  };
}

function buildPillarRow(
  pillar: SciencePillar,
  response: ScienceResponse,
  modes: Record<SciencePillar, 'simple' | 'advanced'>,
): PillarRow {
  const active = response.active?.[pillar];
  const allAlternatives = response.available?.[pillar] ?? [];
  const others = allAlternatives.filter((t: TheorySummary) => t.id !== active?.id);
  const recommendation = response.recommendations?.find(
    (r: PillarRecommendation) => r.pillar === pillar,
  );
  const recommendedName =
    recommendation && recommendation.recommended_id !== active?.id
      ? allAlternatives.find((t: TheorySummary) => t.id === recommendation.recommended_id)?.name ?? ''
      : '';

  const mode = modes[pillar];

  const labels = pillarLabels();
  const questions = pillarQuestions();
  return {
    pillar,
    label: labels[pillar],
    question: questions[pillar],
    modeIsSimple: mode === 'simple',
    modeIsAdvanced: mode === 'advanced',
    hasActive: active != null,
    activeName: active?.name ?? '',
    activeAuthor: active?.author ?? '',
    activeCard: active ? buildTheoryCard(active) : undefined,
    hasRecommendation: !!recommendedName && !!recommendation?.reason,
    recommendationName: recommendedName,
    recommendationReason: recommendation?.reason ?? '',
    hasAlternatives: others.length > 0,
    alternatives: others.slice(0, 5).map(buildTheoryCard),
  };
}

const DEFAULT_MODES: Record<SciencePillar, 'simple' | 'advanced'> = {
  load: 'simple',
  recovery: 'simple',
  prediction: 'simple',
  zones: 'simple',
};

Page({
  data: { ...initialData, pillarModes: { ...DEFAULT_MODES }, tr: buildScienceTr() },

  onLoad() {
    this.setData({ themeClass: themeClassName(), tr: buildScienceTr() });
    void this.refetch();
  },

  onShow() {
    // Guarded theme update: other tabs can't be reached by getCurrentPages()
    // from Settings, so if the user changed theme while on another tab,
    // this is the first chance to apply it. Equality check prevents
    // re-renders on normal tab switches where nothing changed.
    const tc = themeClassName();
    if (tc !== this.data.themeClass) {
      this.setData({ themeClass: tc, chartTheme: tc === 'theme-light' ? 'light' : 'dark' });
    }
    // Locale guard: rebuilds tr when language changed while this tab
    // was not active (same pattern as theme — globalData stores the
    // active locale so we detect drift without a storage read).
    const curLocale = getApp<IAppOption>().globalData.locale;
    const pgMut = this as unknown as Record<string, unknown>;
    if (curLocale !== pgMut._locale) {
      pgMut._locale = curLocale;
      this.setData({ tr: buildScienceTr() });
    }
    applyThemeChrome();
  },

  onRetry() {
    void this.refetch();
  },

  setPillarMode(e: WechatMiniprogram.TouchEvent) {
    const pillar = e.currentTarget.dataset.pillar as SciencePillar | undefined;
    const mode = e.currentTarget.dataset.mode as 'simple' | 'advanced' | undefined;
    if (!pillar || !mode) return;
    const modes = {
      ...(this.data.pillarModes as Record<SciencePillar, 'simple' | 'advanced'>),
      [pillar]: mode,
    };
    // Re-derive the per-pillar boolean flags so WXML doesn't have to do
    // map lookups every render. _response is cached on data so the
    // toggle doesn't re-fetch from the network.
    const response = (this.data as { _response?: ScienceResponse })._response;
    const pillars = response
      ? ALL_PILLARS.map((p) => buildPillarRow(p, response, modes))
      : (this.data.pillars as PillarRow[]);
    this.setData({ pillarModes: modes, pillars });
  },

  onCopyCitation(e: WechatMiniprogram.TouchEvent) {
    const url = e.currentTarget.dataset.url as string | undefined;
    if (url) copyUrlToClipboard(url);
  },

  /**
   * Switch the active theory for one of the four pillars (load /
   * recovery / prediction / zones). Mirrors web's
   * `updateScience({ science: { [pillar]: id } })` — same `PUT
   * /api/science` endpoint, same body shape. We refetch on success so
   * the activeCard / alternatives split flips, and surface the failed-
   * theory id in a toast on error.
   */
  async onSelectTheory(e: WechatMiniprogram.TouchEvent) {
    const pillar = e.currentTarget.dataset.pillar as SciencePillar | undefined;
    const id = e.currentTarget.dataset.id as string | undefined;
    if (!pillar || !id) return;
    if (this.data.selectingPillar) return; // already saving
    this.setData({ selectingPillar: pillar });
    try {
      await apiPut('/api/science', { science: { [pillar]: id } });
      await this.refetch();
    } catch (err) {
      const e2 = err as Partial<ApiError>;
      if (e2?.code === 'UNAUTHENTICATED') return;
      wx.showToast({
        title: e2?.detail ?? t('Failed to switch theory'),
        icon: 'none',
        duration: 2000,
      });
    } finally {
      this.setData({ selectingPillar: '' });
    }
  },

  async refetch() {
    this.setData({ loading: true, errorMessage: '' });
    try {
      const response = await apiGet<ScienceResponse>('/api/science');
      const modes = (this.data.pillarModes as Record<SciencePillar, 'simple' | 'advanced'>)
        ?? { ...DEFAULT_MODES };
      const pillars = ALL_PILLARS.map((p) => buildPillarRow(p, response, modes));
      this.setData({
        loading: false,
        errorMessage: '',
        hasResponse: true,
        pillars,
        activeLabels: response.active_labels,
        hasMultipleLabelSets: response.label_sets.length > 1,
        labelSetCount: response.label_sets.length,
        // Cache raw response on the instance so mode-toggles can rebuild
        // pillar rows without refetching. Underscored to mark as internal.
        _response: response,
      } as Record<string, unknown>);
    } catch (e) {
      const err = e as Partial<ApiError>;
      if (err?.code === 'UNAUTHENTICATED') return;
      const detail = err?.detail ?? String(e);
      this.setData({ loading: false, errorMessage: detail, hasResponse: false });
    }
  },
});
