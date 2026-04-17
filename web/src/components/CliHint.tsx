import { Sparkles } from 'lucide-react';

interface CliHintProps {
  /** The skill command name (e.g., "daily-brief") */
  skill: string;
  /** What the skill does */
  title: string;
  /** Brief description */
  description: string;
}

const PLUGIN_URL = 'https://github.com/dddtc2005/trainsight';

/**
 * Prominent card promoting the Claude Code plugin for AI-powered features.
 * Shown on dashboard pages to drive plugin adoption.
 */
export default function CliHint({ skill, title, description }: CliHintProps) {
  return (
    <div className="mt-6 rounded-xl border border-accent-purple/20 bg-accent-purple/5 px-5 py-4">
      <div className="flex items-start gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-purple/15 mt-0.5">
          <Sparkles className="h-4 w-4 text-accent-purple" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-foreground">{title}</p>
          <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
          <div className="flex items-center gap-3 mt-2.5">
            <code className="rounded-md bg-accent-purple/10 border border-accent-purple/20 px-2.5 py-1 font-data text-xs text-accent-purple">
              /trainsight:{skill}
            </code>
            <a
              href={PLUGIN_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[11px] text-muted-foreground hover:text-accent-purple transition-colors underline underline-offset-2"
            >
              Get the Claude Code Plugin
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
