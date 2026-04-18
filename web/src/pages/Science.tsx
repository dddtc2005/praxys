import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useAuth } from '@/hooks/useAuth';
import { useScience } from '@/contexts/ScienceContext';
import type { SciencePillar, TheorySummary } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Separator } from '@/components/ui/separator';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Trans, useLingui } from '@lingui/react/macro';
import { msg } from '@lingui/core/macro';
import type { MessageDescriptor } from '@lingui/core';

/* ── Pillar config ────────────────────────────────────────────────────── */

const PILLARS: {
  key: SciencePillar;
  label: MessageDescriptor;
  question: MessageDescriptor;
  accent: string;
}[] = [
  { key: 'load', label: msg`Load & Fitness`, question: msg`How does training stress become fitness?`, accent: '#00ff87' },
  { key: 'recovery', label: msg`Recovery`, question: msg`How do we assess readiness to train?`, accent: '#a78bfa' },
  { key: 'prediction', label: msg`Race Prediction`, question: msg`How do we estimate race potential?`, accent: '#f59e0b' },
  { key: 'zones', label: msg`Training Zones`, question: msg`How is intensity classified?`, accent: '#3b82f6' },
];

/* ── Markdown wrapper ─────────────────────────────────────────────────── */

function Md({ children, accent }: { children: string; accent: string }) {
  return (
    <div className="science-markdown" style={{ ['--md-accent' as string]: accent }}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}

/* ── Theory content (shared between active + alternative) ─────────────── */

function TheoryContent({
  theory,
  mode,
  accent,
}: {
  theory: TheorySummary;
  mode: string;
  accent: string;
}) {
  if (mode === 'simple') {
    return (
      <p className="text-sm text-muted-foreground leading-[1.75]">
        {theory.simple_description || theory.description}
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <Md accent={accent}>{theory.advanced_description || theory.description}</Md>

      {theory.citations?.length > 0 && (
        <>
          <Separator />
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-2">
              <Trans>References</Trans>
            </p>
            <ol className="space-y-1 list-decimal list-inside text-xs text-muted-foreground">
              {theory.citations.map((c: any, i: number) => (
                <li key={i} className="leading-relaxed">
                  {c.authors && <span className="text-foreground/80">{c.authors}. </span>}
                  <span className="italic">{c.title}</span>
                  {c.year && ` (${c.year})`}
                  {c.journal && `. ${c.journal}`}
                  {c.url && (
                    <a
                      href={c.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="ml-1 underline decoration-dotted underline-offset-2 hover:text-foreground transition-colors"
                    >
                      <Trans>view</Trans>
                    </a>
                  )}
                </li>
              ))}
            </ol>
          </div>
        </>
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
  if (!active) return null;

  const others = alternatives.filter((t) => t.id !== active.id);

  return (
    <section id={pillar} className="scroll-mt-8">
      <div className="mb-4">
        <h2 className="text-xl font-bold text-foreground tracking-tight">{label}</h2>
        <p className="text-sm text-muted-foreground">{question}</p>
      </div>

      <Tabs defaultValue="simple">
        <TabsList>
          <TabsTrigger value="simple"><Trans>Simple</Trans></TabsTrigger>
          <TabsTrigger value="advanced"><Trans>Advanced</Trans></TabsTrigger>
        </TabsList>

        {(['simple', 'advanced'] as const).map((mode) => (
          <TabsContent key={mode} value={mode} className="space-y-3 mt-4">
            {/* Active theory */}
            <Card style={{ borderLeftWidth: 2, borderLeftColor: accent }}>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <CardTitle className="text-sm">{active.name}</CardTitle>
                  <Badge variant="outline" className="text-[10px]" style={{ borderColor: `${accent}40`, color: accent }}>
                    <Trans>Active</Trans>
                  </Badge>
                </div>
              </CardHeader>
              <CardContent>
                <TheoryContent theory={active} mode={mode} accent={accent} />
              </CardContent>
            </Card>

            {/* Recommendation */}
            {recommendation && recommendation.recommended_id !== active.id && (
              <p className="text-xs text-accent-amber px-1">
                <Trans>Based on your training, we suggest{' '}
                <span className="font-semibold">
                  {alternatives.find((t) => t.id === recommendation.recommended_id)?.name}
                </span>
                {' '}&mdash; {recommendation.reason}</Trans>
              </p>
            )}

            {/* Alternative theories */}
            {others.map((theory) => (
              <Card key={theory.id}>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm">{theory.name}</CardTitle>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => onSelect(pillar, theory.id)}
                    >
                      <Trans>Use this</Trans>
                    </Button>
                  </div>
                </CardHeader>
                <CardContent>
                  <TheoryContent theory={theory} mode={mode} accent={accent} />
                </CardContent>
              </Card>
            ))}
          </TabsContent>
        ))}
      </Tabs>
    </section>
  );
}

/* ── Page ──────────────────────────────────────────────────────────────── */

export default function Science() {
  const { isDemo } = useAuth();
  const { science, loading, updateScience } = useScience();
  const { i18n } = useLingui();

  if (loading) {
    return (
      <div className="space-y-8 py-6">
        <div>
          <Skeleton className="h-8 w-44" />
          <Skeleton className="h-4 w-64 mt-2" />
        </div>
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-48 rounded-2xl" />
        ))}
      </div>
    );
  }

  if (!science) {
    return (
      <Card className="text-center">
        <CardContent className="pt-6">
          <p className="text-destructive font-semibold"><Trans>Failed to load science data</Trans></p>
        </CardContent>
      </Card>
    );
  }

  const recs = science.recommendations ?? [];

  return (
    <div>
      <div className="mb-10">
        <h1 className="text-2xl font-bold text-foreground"><Trans>Training Science</Trans></h1>
        <p className="text-sm text-muted-foreground mt-1 max-w-lg">
          <Trans>Four pillars power your analysis. Each uses a published theory you can
          understand, verify, and change.</Trans>
        </p>
      </div>

      <div className="space-y-14">
        {PILLARS.map((p) => (
          <PillarSection
            key={p.key}
            pillar={p.key}
            label={i18n._(p.label)}
            question={i18n._(p.question)}
            accent={p.accent}
            active={science.active[p.key]}
            alternatives={science.available[p.key] ?? []}
            recommendation={recs.find((r) => r.pillar === p.key)}
            onSelect={isDemo ? () => {} : (pillar, id) => updateScience({ science: { [pillar]: id } })}
          />
        ))}
      </div>

      <Separator className="mt-14 mb-6" />
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-foreground"><Trans>Zone Labels</Trans></p>
          <p className="text-xs text-muted-foreground mt-0.5">
            <Trans>Cosmetic &mdash; changes names and colors without affecting calculations</Trans>
          </p>
        </div>
        <ToggleGroup
          value={[science.active_labels]}
          onValueChange={(v) => { if (v.length && !isDemo) updateScience({ zone_labels: v[v.length - 1] }); }}
        >
          {(science.label_sets ?? []).map((ls) => (
            <ToggleGroupItem key={ls.id} value={ls.id} size="sm">
              {ls.name}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>
    </div>
  );
}
