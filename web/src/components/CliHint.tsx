import { Terminal } from 'lucide-react';

interface CliHintProps {
  skill: string;
  description: string;
}

/**
 * Subtle hint suggesting a CLI plugin skill for deeper analysis.
 * Shown at the bottom of dashboard pages.
 */
export default function CliHint({ skill, description }: CliHintProps) {
  return (
    <div className="flex items-center gap-2 rounded-lg bg-muted/50 px-4 py-2.5 mt-6">
      <Terminal className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <p className="text-[11px] text-muted-foreground">
        {description}{' '}
        <code className="rounded bg-muted px-1 py-0.5 font-data text-[10px] text-foreground/70">
          /trainsight:{skill}
        </code>
      </p>
    </div>
  );
}
