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
import { t, tFmt } from '../../utils/i18n';

const ALL_PILLARS: SciencePillar[] = ['load', 'recovery', 'prediction', 'zones'];

const PILLAR_NUMS: Record<SciencePillar, string> = {
  load: '01',
  recovery: '02',
  prediction: '03',
  zones: '04',
};

function buildScienceTr() {
  return {
    navTitle: t('Training science'),
    failedToLoad: t('Failed to load'),
    retry: t('Retry'),
    eyebrow: t('Four-pillar framework'),
    intro: t(
      'Each pillar runs a published theory you can read, verify, and swap. Praxys interprets your data through whichever framework you choose.',
    ),
    references: t('References'),
    tapToCopy: t('tap to copy URL'),
    zoneLabels: t('Zone labels'),
    currentlyUsing: t('Currently using'),
    showAdvanced: t('Show methodology details'),
    hideAdvanced: t('Hide methodology details'),
    cancelPreview: t('Cancel preview'),
    activeTag: t('Active'),
    previewingTag: t('Previewing'),
    recommendedTag: t('Recommended'),
    by: t('by'),
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
    load: t('Translates training stress into fitness.'),
    recovery: t("Reads readiness from the body's signals."),
    prediction: t('Estimates race performance from current fitness.'),
    zones: t('Defines what counts as easy, threshold, hard.'),
  };
}

interface CitationRow {
  display: string;
  url: string;
  hasUrl: boolean;
}

interface ChicletRow {
  id: string;
  name: string;
  isActive: boolean;
  isPreviewing: boolean;
  isRecommended: boolean;
  /** Combined modifier string for {{ }} interpolation in WXML. */
  modifier: string;
}

interface PillarTab {
  pillar: SciencePillar;
  num: string;
  label: string;
  isFocused: boolean;
  recAvailable: boolean;
}

interface DetailView {
  pillar: SciencePillar;
  num: string;
  label: string;
  question: string;
  hasActive: boolean;
  chiclets: ChicletRow[];
  /** Theory currently shown in the body (active or previewed). */
  shownAuthor: string;
  shownAuthorVisible: boolean;
  shownDescription: string;
  shownAdvancedHtml: string;
  hasAdvanced: boolean;
  citations: CitationRow[];
  hasCitations: boolean;
  /** Recommendation hint visibility + content. */
  hasRecHint: boolean;
  recName: string;
  recReason: string;
  /** Preview-commit row visibility + button label. */
  isPreviewMode: boolean;
  switchLabel: string;
}

interface SciState {
  themeClass: string;
  loading: boolean;
  errorMessage: string;
  hasResponse: boolean;
  tabs: PillarTab[];
  detail: DetailView | null;
  showAdvanced: boolean;
  activeLabels: string;
  hasMultipleLabelSets: boolean;
  labelSetCount: number;
  /** Pre-formatted "{count} label sets available — switch on the web."
   *  string. Computed at refetch time so the count interpolates and the
   *  whole sentence stays translatable as a single message. */
  labelSetsAvailableText: string;
  /** Pillar currently mid-save, so the Switch button can disable. */
  selectingPillar: SciencePillar | '';
}

const initialData: SciState = {
  themeClass: getApp<IAppOption>().globalData.themeClass,
  loading: true,
  errorMessage: '',
  hasResponse: false,
  tabs: [],
  detail: null,
  showAdvanced: false,
  activeLabels: '',
  hasMultipleLabelSets: false,
  labelSetCount: 0,
  labelSetsAvailableText: '',
  selectingPillar: '',
};

/** Format a citation object as a readable line. Loose YAML schema means
 * we narrow per-field with typeof guards. URLs surface as tappable
 * copy-to-clipboard rows separately because <rich-text> <a> tags don't
 * navigate in mini programs. */
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

function buildCitations(theory: TheorySummary): CitationRow[] {
  return (theory.citations ?? []).map((c) => {
    const url = typeof c.url === 'string' ? c.url : '';
    return { display: formatCitation(c), url, hasUrl: !!url };
  });
}

function chicletModifier(isActive: boolean, isPreviewing: boolean, isRecommended: boolean): string {
  if (isPreviewing) return 'sci-chiclet--previewing';
  if (isActive) return 'sci-chiclet--active';
  if (isRecommended) return 'sci-chiclet--recommended';
  return '';
}

function buildPillarTabs(
  response: ScienceResponse,
  focused: SciencePillar,
  labels: Record<SciencePillar, string>,
): PillarTab[] {
  return ALL_PILLARS.map((pillar) => {
    const active = response.active?.[pillar];
    const rec = response.recommendations?.find((r) => r.pillar === pillar);
    const recAvailable = !!(rec && rec.recommended_id !== active?.id);
    return {
      pillar,
      num: PILLAR_NUMS[pillar],
      label: labels[pillar],
      isFocused: pillar === focused,
      recAvailable,
    };
  });
}

function buildDetail(
  pillar: SciencePillar,
  response: ScienceResponse,
  previewId: string | undefined,
  labels: Record<SciencePillar, string>,
  questions: Record<SciencePillar, string>,
  tr: { switchToFmt: string },
): DetailView {
  const active = response.active?.[pillar];
  const alternatives = response.available?.[pillar] ?? [];
  const recommendation: PillarRecommendation | undefined =
    response.recommendations?.find((r) => r.pillar === pillar);

  const isPreviewMode = !!(previewId && previewId !== active?.id);
  const previewedTheory = previewId ? alternatives.find((t) => t.id === previewId) : undefined;
  const shownTheory: TheorySummary | undefined = isPreviewMode ? previewedTheory : active;

  const chiclets: ChicletRow[] = alternatives.map((t) => {
    const isActive = t.id === active?.id;
    const isPreviewing = t.id === previewId && previewId !== active?.id;
    const isRecommended =
      !!recommendation && recommendation.recommended_id === t.id && t.id !== active?.id;
    return {
      id: t.id,
      name: t.name,
      isActive,
      isPreviewing,
      isRecommended,
      modifier: chicletModifier(isActive, isPreviewing, isRecommended),
    };
  });

  const recommendedDifferent =
    !!recommendation && recommendation.recommended_id !== active?.id;
  const recommendedTheory = recommendedDifferent
    ? alternatives.find((t) => t.id === recommendation!.recommended_id)
    : undefined;
  // Hide the rec hint once the user starts previewing the recommended
  // theory — the chiclet's amber halo plus the body's "Previewing" tag
  // already carry the message, and a third surface would crowd the
  // staged Switch CTA.
  const hasRecHint =
    !!recommendedDifferent &&
    !!recommendedTheory &&
    previewId !== recommendation!.recommended_id;

  let advancedHtml = '';
  let hasAdvanced = false;
  if (shownTheory) {
    const src = shownTheory.advanced_description || shownTheory.description || '';
    const parsed = parseMarkdown(src);
    advancedHtml = parsed.html;
    hasAdvanced = !!advancedHtml;
  }
  const citations = shownTheory ? buildCitations(shownTheory) : [];

  return {
    pillar,
    num: PILLAR_NUMS[pillar],
    label: labels[pillar],
    question: questions[pillar],
    hasActive: !!active,
    chiclets,
    shownAuthor: shownTheory?.author ?? '',
    shownAuthorVisible: !!shownTheory && !!shownTheory.author && shownTheory.author !== 'system',
    shownDescription: shownTheory?.simple_description || shownTheory?.description || '',
    shownAdvancedHtml: advancedHtml,
    hasAdvanced,
    citations,
    hasCitations: citations.length > 0,
    hasRecHint,
    recName: recommendedTheory?.name ?? '',
    recReason: recommendation?.reason ?? '',
    isPreviewMode,
    switchLabel: previewedTheory ? tFmt(tr.switchToFmt, previewedTheory.name) : '',
  };
}

Page({
  data: {
    ...initialData,
    focused: 'load' as SciencePillar,
    previewing: {} as Partial<Record<SciencePillar, string>>,
    tr: buildScienceTr(),
  },

  onLoad() {
    this.setData({ themeClass: themeClassName(), tr: buildScienceTr() });
    void this.refetch();
  },

  onShow() {
    // Guarded theme update: other tabs can't be reached by getCurrentPages()
    // from Settings, so if the user changed theme while on another tab,
    // this is the first chance to apply it.
    const tc = themeClassName();
    if (tc !== this.data.themeClass) this.setData({ themeClass: tc });
    // Locale guard: rebuild tr / labels / questions when language changed
    // while this tab was not active (same pattern as theme).
    const curLocale = getApp<IAppOption>().globalData.locale;
    const pgMut = this as unknown as Record<string, unknown>;
    if (curLocale !== pgMut._locale) {
      pgMut._locale = curLocale;
      this.setData({ tr: buildScienceTr() });
      this.rebuildView();
    }
    applyThemeChrome();
  },

  onRetry() {
    void this.refetch();
  },

  onSelectPillar(e: WechatMiniprogram.TouchEvent) {
    const pillar = e.currentTarget.dataset.pillar as SciencePillar | undefined;
    if (!pillar || pillar === this.data.focused) return;
    this.setData({ focused: pillar, showAdvanced: false });
    this.rebuildView();
  },

  onChicletTap(e: WechatMiniprogram.TouchEvent) {
    const id = e.currentTarget.dataset.id as string | undefined;
    if (!id) return;
    const focused = this.data.focused as SciencePillar;
    const response = (this.data as { _response?: ScienceResponse })._response;
    const active = response?.active?.[focused];
    const previewing = { ...(this.data.previewing as Partial<Record<SciencePillar, string>>) };
    if (id === active?.id) {
      // Tapping the active chiclet cancels any preview.
      delete previewing[focused];
    } else {
      previewing[focused] = id;
    }
    this.setData({ previewing, showAdvanced: false });
    this.rebuildView();
  },

  onCancelPreview() {
    const focused = this.data.focused as SciencePillar;
    const previewing = { ...(this.data.previewing as Partial<Record<SciencePillar, string>>) };
    delete previewing[focused];
    this.setData({ previewing });
    this.rebuildView();
  },

  onToggleAdvanced() {
    this.setData({ showAdvanced: !this.data.showAdvanced });
  },

  onCopyCitation(e: WechatMiniprogram.TouchEvent) {
    const url = e.currentTarget.dataset.url as string | undefined;
    if (url) copyUrlToClipboard(url);
  },

  /** Commit the previewed theory: PUT /api/science, then refetch so
   * `active[pillar]` flips. Mirrors web's preview-then-commit flow.
   * `refetch()` catches its own errors and surfaces them via the page-
   * level error state, so a refetch failure after a successful PUT
   * doesn't fall into this catch block (which would mislabel a saved
   * write as "Failed to switch theory"). */
  async onSwitchTheory() {
    const focused = this.data.focused as SciencePillar;
    const previewing = this.data.previewing as Partial<Record<SciencePillar, string>>;
    const id = previewing[focused];
    if (!id) return;
    if (this.data.selectingPillar) return;
    this.setData({ selectingPillar: focused });
    try {
      await apiPut('/api/science', { science: { [focused]: id } });
      // Clear preview before refetch so the rebuilt view shows the new
      // active state (not lingering preview chrome).
      const next = { ...previewing };
      delete next[focused];
      this.setData({ previewing: next });
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

  /** Rebuild tabs + detail from cached `_response` without refetching. */
  rebuildView() {
    const response = (this.data as { _response?: ScienceResponse })._response;
    if (!response) return;
    const focused = this.data.focused as SciencePillar;
    const previewing = this.data.previewing as Partial<Record<SciencePillar, string>>;
    const labels = pillarLabels();
    const questions = pillarQuestions();
    const tabs = buildPillarTabs(response, focused, labels);
    const detail = buildDetail(focused, response, previewing[focused], labels, questions, {
      switchToFmt: t('Switch to {0}'),
    });
    this.setData({ tabs, detail });
  },

  async refetch() {
    this.setData({ loading: true, errorMessage: '' });
    try {
      const response = await apiGet<ScienceResponse>('/api/science');
      const focused = this.data.focused as SciencePillar;
      const previewing = this.data.previewing as Partial<Record<SciencePillar, string>>;
      const labels = pillarLabels();
      const questions = pillarQuestions();
      const tabs = buildPillarTabs(response, focused, labels);
      const detail = buildDetail(focused, response, previewing[focused], labels, questions, {
        switchToFmt: t('Switch to {0}'),
      });
      this.setData({
        loading: false,
        errorMessage: '',
        hasResponse: true,
        tabs,
        detail,
        activeLabels: response.active_labels,
        hasMultipleLabelSets: response.label_sets.length > 1,
        labelSetCount: response.label_sets.length,
        labelSetsAvailableText: tFmt(
          '{0} label sets available — switch on the web.',
          response.label_sets.length,
        ),
        // Cache raw response so pillar/chiclet changes can rebuild the
        // view without refetching.
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
