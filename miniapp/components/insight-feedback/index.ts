import type { InsightFeedbackVote } from '../../types/api';
import { t } from '../../utils/i18n';
import type { ApiError } from '../../utils/api-client';
import { submitInsightFeedback } from '../../utils/insights';

function translations() {
  return {
    question: t('Was this insight useful?'),
    helpful: t('Helpful'),
    notHelpful: t('Not helpful'),
    commentPlaceholder: t('What was useful or missing?'),
    send: t('Send'),
    sending: t('Sending...'),
    cancel: t('Cancel'),
    sent: t('Sent'),
    error: t("Couldn't send feedback. Try again."),
    stale: t('This insight changed. Refresh the page before sending feedback.'),
  };
}

Component({
  options: { addGlobalClass: true },

  properties: {
    insightType: { type: String as StringConstructor, value: '' },
    datasetHash: { type: String as StringConstructor, value: '' },
    initialVote: { type: String as StringConstructor, value: '' },
  },

  data: {
    selectedVote: '' as InsightFeedbackVote | '',
    formOpen: false,
    comment: '',
    commentLength: 0,
    submitting: false,
    sent: false,
    stale: false,
    error: '',
    tr: translations(),
  },

  observers: {
    'datasetHash, initialVote'(datasetHash: string, initialVote: string) {
      const validVote = initialVote === 'up' || initialVote === 'down';
      this.setData({
        selectedVote: validVote ? initialVote : '',
        sent: Boolean(datasetHash && validVote),
        stale: false,
        submitting: false,
        formOpen: false,
        comment: '',
        commentLength: 0,
        error: '',
      });
    },
  },

  lifetimes: {
    attached() {
      this.setData({ tr: translations() });
    },
  },

  methods: {
    chooseVote(vote: InsightFeedbackVote) {
      if (this.data.sent || this.data.submitting || this.data.stale) return;
      if (this.data.selectedVote === vote && this.data.formOpen) {
        this.setData({
          selectedVote: '',
          formOpen: false,
          comment: '',
          commentLength: 0,
          error: '',
        });
        return;
      }
      this.setData({ selectedVote: vote, formOpen: true, error: '' });
    },

    onHelpful() {
      this.chooseVote('up');
    },

    onNotHelpful() {
      this.chooseVote('down');
    },

    onCommentInput(event: WechatMiniprogram.Input) {
      const value = String(event.detail.value ?? '').slice(0, 200);
      this.setData({ comment: value, commentLength: value.length });
    },

    onCancel() {
      if (this.data.submitting) return;
      this.setData({
        selectedVote: '',
        formOpen: false,
        comment: '',
        commentLength: 0,
        error: '',
      });
    },

    async onSubmit() {
      const vote = this.data.selectedVote as InsightFeedbackVote | '';
      const datasetHash = this.data.datasetHash as string;
      const insightType = this.data.insightType as string;
      if (!vote || !datasetHash || !insightType || this.data.submitting || this.data.stale) return;

      const requestIsCurrent = () => (
        this.data.insightType === insightType
        && this.data.datasetHash === datasetHash
      );
      this.setData({ submitting: true, error: '' });
      try {
        const response = await submitInsightFeedback(
          insightType,
          datasetHash,
          vote,
          (this.data.comment as string).trim() || null,
        );
        if (!requestIsCurrent()) return;
        this.setData({
          selectedVote: response.feedback.vote,
          sent: true,
          formOpen: false,
          comment: '',
          commentLength: 0,
        });
      } catch (error) {
        if (!requestIsCurrent()) return;
        const apiError = error as Partial<ApiError>;
        if (
          apiError.status === 409
          && (
            apiError.detail === 'INSIGHT_FEEDBACK_STALE'
            || apiError.detail === 'INSIGHT_FEEDBACK_UNVERSIONED'
          )
        ) {
          this.setData({ stale: true, error: this.data.tr.stale });
          this.triggerEvent('stale');
        } else {
          this.setData({ error: this.data.tr.error });
        }
      } finally {
        if (requestIsCurrent()) this.setData({ submitting: false });
      }
    },
  },
});
