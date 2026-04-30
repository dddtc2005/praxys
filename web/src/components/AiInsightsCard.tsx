import { useApi } from '@/hooks/useApi';
import type { AiInsight } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { ChevronDown, Sparkles, CheckCircle2, AlertTriangle, Minus } from 'lucide-react';
import { useState } from 'react';
import { Trans, Plural, useLingui } from '@lingui/react/macro';
import { useLocale } from '@/contexts/LocaleContext';

interface Props {
  insightType: string;
}

function FindingIcon({ type }: { type: string }) {
  if (type === 'positive') {
    return <CheckCircle2 className="h-4 w-4 shrink-0 text-primary" />;
  }
  if (type === 'warning') {
    return <AlertTriangle className="h-4 w-4 shrink-0 text-accent-amber" />;
  }
  return <Minus className="h-4 w-4 shrink-0 text-muted-foreground" />;
}

function timeAgo(isoDate: string, locale: string): string {
  const diff = Date.now() - new Date(isoDate).getTime();
  const rtf = new Intl.RelativeTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', { style: 'short' });
  const mins = Math.floor(diff / 60_000);
  if (mins < 60) return rtf.format(-mins, 'minute');
  const hours = Math.floor(mins / 60);
  if (hours < 24) return rtf.format(-hours, 'hour');
  const days = Math.floor(hours / 24);
  return rtf.format(-days, 'day');
}

export default function AiInsightsCard({ insightType }: Props) {
  const { data } = useApi<{ insight: AiInsight | null }>(`/api/insights/${insightType}`);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const { locale } = useLocale();
  const {} = useLingui();

  const insight = data?.insight;
  if (!insight) return null;

  // Prefer the active-locale translation when present; fall back to the
  // top-level English fields. Issue #103.
  const localized = (locale === 'zh' && insight.translations?.zh) || insight;
  const headline = localized.headline;
  const summary = localized.summary;
  const findings = localized.findings ?? insight.findings ?? [];
  const recommendations = localized.recommendations ?? insight.recommendations ?? [];

  return (
    <Card className="border-accent-purple/30 bg-accent-purple/[0.03]">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent-purple/15 text-accent-purple">
              <Sparkles className="h-3.5 w-3.5" />
            </div>
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-accent-purple">
              <Trans>Praxys Coach</Trans>
            </CardTitle>
          </div>
          {insight.generated_at && (
            <span className="text-[10px] text-muted-foreground font-data">
              {timeAgo(insight.generated_at, locale)}
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        {/* Headline */}
        <p className="text-sm font-semibold text-foreground mb-2">
          {headline}
        </p>

        {/* Summary (always visible) */}
        <p className="text-sm text-muted-foreground leading-relaxed mb-3 whitespace-pre-line">
          {summary}
        </p>

        {/* Expandable details */}
        {(findings.length > 0 || recommendations.length > 0) && (
          <Collapsible open={detailsOpen} onOpenChange={setDetailsOpen}>
            <CollapsibleTrigger className="flex items-center gap-1 text-xs text-accent-purple hover:text-accent-purple/80 transition-colors mb-2">
              <ChevronDown className={`h-3.5 w-3.5 transition-transform ${detailsOpen ? 'rotate-180' : ''}`} />
              {detailsOpen ? (
                <Trans>Hide details</Trans>
              ) : (
                <span>
                  <Plural
                    value={findings.length}
                    one="# finding"
                    other="# findings"
                  />
                  {', '}
                  <Plural
                    value={recommendations.length}
                    one="# recommendation"
                    other="# recommendations"
                  />
                </span>
              )}
            </CollapsibleTrigger>
            <CollapsibleContent>
              {/* Findings */}
              {findings.length > 0 && (
                <div className="space-y-1.5 mb-3">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground"><Trans>Findings</Trans></p>
                  {findings.map((f, i) => (
                    <div key={i} className="flex items-start gap-2 text-sm text-muted-foreground">
                      <FindingIcon type={f.type} />
                      <span className={f.type === 'warning' ? 'text-foreground' : ''}>{f.text}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Recommendations */}
              {recommendations.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground"><Trans>Recommendations</Trans></p>
                  {recommendations.map((r, i) => (
                    <div key={i} className="flex items-start gap-2 text-sm text-foreground">
                      <span className="text-accent-purple font-bold shrink-0">{i + 1}.</span>
                      <span>{r}</span>
                    </div>
                  ))}
                </div>
              )}
            </CollapsibleContent>
          </Collapsible>
        )}
      </CardContent>
    </Card>
  );
}
