import { t } from '../../utils/i18n';

Component({
  options: { addGlobalClass: true },

  properties: {
    /** 'loading' | 'error' | 'empty' */
    type: { type: String as StringConstructor, value: 'loading' },
    /** Headline shown in error and empty states. */
    headline: { type: String as StringConstructor, value: '' },
    /** Optional sub-text shown under the headline. */
    detail: { type: String as StringConstructor, value: '' },
    /** Show a retry button in the error state. */
    showRetry: { type: Boolean as BooleanConstructor, value: false },
    /** Label for the retry button. Defaults to the i18n'd "Retry". */
    retryLabel: { type: String as StringConstructor, value: '' },
  },

  data: {},

  lifetimes: {
    ready() {
      // Default retryLabel to the translated "Retry" if the caller
      // didn't pass a custom label.
      if (!this.data.retryLabel) {
        this.setData({ retryLabel: t('Retry') });
      }
    },
  },

  methods: {
    onRetryTap() {
      this.triggerEvent('retry');
    },
  },
});
