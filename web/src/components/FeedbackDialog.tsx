import { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { API_BASE, getAuthHeaders } from '@/hooks/useApi';
import { WEB_VERSION } from '@/lib/version';
import { useLocale } from '@/contexts/LocaleContext';
import type { FeedbackKind, FeedbackResponse } from '@/types/api';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Check } from 'lucide-react';
import { Trans, useLingui } from '@lingui/react/macro';
import { msg } from '@lingui/core/macro';
import type { MessageDescriptor } from '@lingui/core';

const MESSAGE_MAX = 5000;

const KIND_OPTIONS: { value: FeedbackKind; label: MessageDescriptor }[] = [
  { value: 'bug', label: msg`Bug report` },
  { value: 'feature', label: msg`Feature request` },
  { value: 'other', label: msg`General feedback` },
];

interface FeedbackDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Preselected category when the dialog opens. Defaults to a bug report. */
  defaultKind?: FeedbackKind;
}

/**
 * Reusable "Send feedback" dialog. Captures the user's report plus basic,
 * non-PII diagnostics (current route, app version, browser, viewport, locale)
 * so the backend triage step has context without the user having to describe
 * their environment. The server scrubs everything before anything is filed
 * to the issue tracker.
 */
export default function FeedbackDialog({ open, onOpenChange, defaultKind = 'bug' }: FeedbackDialogProps) {
  const { t, i18n } = useLingui();
  const { locale } = useLocale();
  const location = useLocation();
  const [kind, setKind] = useState<FeedbackKind>(defaultKind);
  const [message, setMessage] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setMessage('');
    setKind(defaultKind);
    setDone(false);
    setError(null);
    setSubmitting(false);
  };

  const handleOpenChange = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const captureContext = (): Record<string, string | number> => ({
    page: location.pathname,
    app_version: WEB_VERSION,
    user_agent: navigator.userAgent,
    viewport: `${window.innerWidth}x${window.innerHeight}`,
    locale,
  });

  const submit = async () => {
    const trimmed = message.trim();
    if (!trimmed) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/feedback`, {
        method: 'POST',
        headers: { ...(getAuthHeaders() as Record<string, string>), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          kind,
          message: trimmed.slice(0, MESSAGE_MAX),
          context: captureContext(),
          locale,
        }),
      });
      if (res.status === 429) {
        setError(t`You've sent several reports recently — please wait a few minutes before sending more.`);
        return;
      }
      if (!res.ok) {
        setError(t`Couldn't send your feedback. Please try again.`);
        return;
      }
      (await res.json()) as FeedbackResponse;
      setDone(true);
    } catch {
      setError(t`Network error — please try again.`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            <Trans>Send feedback</Trans>
          </DialogTitle>
          <DialogDescription>
            <Trans>Found a bug or have an idea? Tell us — reports are reviewed and triaged automatically.</Trans>
          </DialogDescription>
        </DialogHeader>

        {done ? (
          <div className="flex flex-col items-center gap-2 py-6 text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/15 text-primary">
              <Check className="h-5 w-5" />
            </div>
            <p className="text-sm font-medium">
              <Trans>Thanks for the feedback!</Trans>
            </p>
            <p className="text-sm text-muted-foreground">
              <Trans>We've logged it and will take a look.</Trans>
            </p>
            <Button className="mt-2" onClick={() => handleOpenChange(false)}>
              <Trans>Close</Trans>
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="feedback-kind">
                <Trans>Type</Trans>
              </Label>
              <Select value={kind} onValueChange={(v) => v && setKind(v as FeedbackKind)}>
                <SelectTrigger id="feedback-kind" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {KIND_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {i18n._(opt.label)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="feedback-message">
                <Trans>Details</Trans>
              </Label>
              <textarea
                id="feedback-message"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                maxLength={MESSAGE_MAX}
                rows={5}
                placeholder={t`What happened, or what would you like to see?`}
                className="w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50 dark:bg-input/30"
                disabled={submitting}
              />
              <p className="text-right text-xs text-muted-foreground font-data">
                {message.length}/{MESSAGE_MAX}
              </p>
            </div>

            <p className="text-xs text-muted-foreground">
              <Trans>
                We attach basic diagnostics (page, app version, browser) and automatically remove personal details
                before sharing with our issue tracker.
              </Trans>
            </p>

            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <DialogFooter>
              <Button variant="outline" onClick={() => handleOpenChange(false)} disabled={submitting}>
                <Trans>Cancel</Trans>
              </Button>
              <Button onClick={submit} disabled={submitting || !message.trim()}>
                {submitting ? <Trans>Sending…</Trans> : <Trans>Send feedback</Trans>}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
