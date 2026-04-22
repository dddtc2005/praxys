import { Card, CardContent } from '@/components/ui/card';
import { msg } from '@lingui/core/macro';
import { useLingui } from '@lingui/react/macro';
import type { MessageDescriptor } from '@lingui/core';

interface Props {
  recommendation: string;
  reason: string;
}

type SignalColor = 'green' | 'amber' | 'red';

const SIGNAL_MAP: Record<string, { label: MessageDescriptor; subtitle: MessageDescriptor; color: SignalColor }> = {
  follow_plan: { label: msg`GO`, subtitle: msg`Follow Plan`, color: 'green' },
  easy: { label: msg`EASY`, subtitle: msg`Go Easy`, color: 'amber' },
  modify: { label: msg`MODIFY`, subtitle: msg`Adjust Workout`, color: 'amber' },
  reduce_intensity: { label: msg`CAUTION`, subtitle: msg`Reduce Intensity`, color: 'amber' },
  rest: { label: msg`REST`, subtitle: msg`Recovery Day`, color: 'red' },
};

const COLOR_CLASSES = {
  green: {
    text: 'text-primary',
    bg: 'bg-primary',
    shadow: 'shadow-[0_0_40px_rgba(0,255,135,0.3)]',
    ring: 'ring-accent-green/30',
    glow: 'animate-pulse',
  },
  amber: {
    text: 'text-accent-amber',
    bg: 'bg-accent-amber',
    shadow: 'shadow-[0_0_40px_rgba(245,158,11,0.3)]',
    ring: 'ring-accent-amber/30',
    glow: 'animate-pulse',
  },
  red: {
    text: 'text-destructive',
    bg: 'bg-destructive',
    shadow: 'shadow-[0_0_40px_rgba(239,68,68,0.3)]',
    ring: 'ring-accent-red/30',
    glow: 'animate-pulse',
  },
};

export default function SignalHero({ recommendation, reason }: Props) {
  const { i18n } = useLingui();
  const signal = SIGNAL_MAP[recommendation] ?? SIGNAL_MAP.follow_plan;
  const colors = COLOR_CLASSES[signal.color];

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex flex-col items-center gap-4 py-4">
          {/* Circular indicator */}
          <div
            className={`relative flex h-32 w-32 items-center justify-center rounded-full ring-4 ${colors.ring} ${colors.shadow}`}
          >
            {/* Pulsing glow ring */}
            <div
              className={`absolute inset-0 rounded-full ${colors.bg} opacity-10 ${colors.glow}`}
            />
            <span className={`relative text-3xl font-bold font-data tracking-wider ${colors.text}`}>
              {i18n._(signal.label)}
            </span>
          </div>

          {/* Subtitle */}
          <p className={`text-lg font-semibold ${colors.text}`}>{i18n._(signal.subtitle)}</p>

          {/* Reason */}
          <p className="max-w-md text-center text-sm text-muted-foreground">{reason}</p>
        </div>
      </CardContent>
    </Card>
  );
}
