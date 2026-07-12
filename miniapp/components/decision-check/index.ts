import type { TodayFeedbackResponse } from '../../types/api';
import { t } from '../../utils/i18n';
import {
  claimTodayDecisionCheck,
  confirmTodayDecisionCheck,
  productEventStorageScope,
  recordProductEvent,
} from '../../utils/product-events';

const STORAGE_KEY = 'praxys.today-decision-check.last-shown'; // i18n-allow
const CADENCE_MS = 7 * 24 * 60 * 60 * 1000;

function cadenceStorageKey(): string {
  return `${STORAGE_KEY}:${productEventStorageScope()}`;
}

function translations() {
  return {
    eyebrow: t('Quick check'),
    heading: t("Did today's brief affect your training decision?"),
    detail: t('One tap helps us make this brief more useful.'),
    dismiss: t('Dismiss'),
    thanks: t('Thanks - that helps us improve Today.'),
    error: t("Couldn't send feedback. Try again."),
  };
}

function options() {
  return [
    { value: 'changed_plan', label: t("Changed what I'll do") },
    { value: 'confirmed_plan', label: t('Confirmed what I planned') },
    { value: 'not_helpful', label: t("Didn't help today") },
    { value: 'not_training', label: t("I'm not training today") },
  ];
}

Component({
  options: { addGlobalClass: true },

  properties: {
    eligible: { type: Boolean as BooleanConstructor, value: false },
  },

  data: {
    visible: false,
    expanded: false,
    submitted: false,
    submitting: false,
    submitError: '',
    claiming: false,
    tr: translations(),
    options: options(),
  },

  observers: {
    eligible(eligible: boolean) {
      if (!eligible) {
        this.setData({ visible: false, expanded: false });
        return;
      }
      this.tryShow();
    },
  },

  lifetimes: {
    attached() {
      this.setData({ tr: translations(), options: options() });
      if (this.data.eligible) this.tryShow();
    },
  },

  methods: {
    async tryShow() {
      if (this.data.visible || this.data.submitted || this.data.claiming) return;
      const now = Date.now();
      let lastShown = 0;
      try {
        lastShown = Number(wx.getStorageSync<number>(cadenceStorageKey()) || 0);
      } catch {
        lastShown = 0;
      }
      if (Number.isFinite(lastShown) && now - lastShown < CADENCE_MS) return;

      this.setData({ claiming: true });
      const claim = await claimTodayDecisionCheck();
      if (
        !this.data.eligible
        || claim === null
        || !claim.accepted
        || claim.duplicate
      ) {
        this.setData({ claiming: false });
        return;
      }

      this.setData({ claiming: false, visible: true, expanded: false }, () => {
        this.persistCadence();
        this.confirmShown();
      });
    },

    persistCadence() {
      try {
        wx.setStorageSync(cadenceStorageKey(), Date.now());
      } catch {
        // Cadence persistence is best-effort when local storage is unavailable.
      }
    },

    confirmShown() {
      void confirmTodayDecisionCheck();
    },

    onToggle() {
      this.setData({ expanded: !this.data.expanded });
    },

    onDismiss() {
      this.setData({ visible: false, expanded: false });
      this.confirmShown();
    },

    async onResponse(event: WechatMiniprogram.TouchEvent) {
      const response = event.currentTarget.dataset.response as TodayFeedbackResponse;
      if (!response || this.data.submitting) return;
      this.setData({ submitting: true, submitError: '' });
      const result = await recordProductEvent('today_feedback_submitted', response);
      if (result?.accepted) {
        this.persistCadence();
        this.setData({ submitted: true, submitting: false, expanded: false });
        return;
      }
      this.setData({ submitting: false, submitError: this.data.tr.error });
    },
  },
});
