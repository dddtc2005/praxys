import { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { formatTime, parseTimeToSeconds } from '@/lib/format';
import { Trans, useLingui } from '@lingui/react/macro';

type DistanceKey = '5k' | '10k' | 'half' | 'marathon' | '50k' | '50mi' | '100k' | '100mi';

type GoalType = 'race' | 'continuous';

interface GoalEditorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialType: GoalType;
  initialRaceDate: string;
  initialDistance: string;
  initialTargetTime: number | null;
  onSave: (goal: { race_date: string; distance: string; target_time_sec: number }) => Promise<void>;
}

export default function GoalEditor({
  open,
  onOpenChange,
  initialType,
  initialRaceDate,
  initialDistance,
  initialTargetTime,
  onSave,
}: GoalEditorProps) {
  const { t } = useLingui();
  const [goalType, setGoalType] = useState<GoalType>(initialType);
  const [raceDate, setRaceDate] = useState(initialRaceDate);
  const [distance, setDistance] = useState(initialDistance || 'marathon');
  const [targetTimeInput, setTargetTimeInput] = useState(
    initialTargetTime ? formatTime(initialTargetTime) : ''
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const DISTANCES: { value: DistanceKey; label: string; placeholder: string }[] = [
    { value: '5k', label: t`5K`, placeholder: t`e.g. 20:00` },
    { value: '10k', label: t`10K`, placeholder: t`e.g. 42:00` },
    { value: 'half', label: t`Half`, placeholder: t`e.g. 1:30:00` },
    { value: 'marathon', label: t`Marathon`, placeholder: t`e.g. 3:00:00` },
    { value: '50k', label: t`50K`, placeholder: t`e.g. 4:30:00` },
    { value: '50mi', label: t`50 Mi`, placeholder: t`e.g. 8:00:00` },
    { value: '100k', label: t`100K`, placeholder: t`e.g. 12:00:00` },
    { value: '100mi', label: t`100 Mi`, placeholder: t`e.g. 24:00:00` },
  ];

  const selectedDist = DISTANCES.find((d) => d.value === distance);

  const handleSave = async () => {
    setError('');

    if (goalType === 'race' && !raceDate) {
      setError(t`Race date is required`);
      return;
    }

    const targetTimeSec = parseTimeToSeconds(targetTimeInput);
    if (targetTimeInput.trim() && targetTimeSec === null) {
      setError(t`Invalid time format. Use H:MM:SS or H:MM`);
      return;
    }

    setSaving(true);
    try {
      await onSave({
        race_date: goalType === 'race' ? raceDate : '',
        distance,
        target_time_sec: targetTimeSec || 0,
      });
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : t`Failed to save goal`);
    }
    setSaving(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            <Trans>Set Your Goal</Trans>
          </DialogTitle>
          <DialogDescription>
            <Trans>Choose a race target or track continuous improvement.</Trans>
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 py-2">
          {/* Goal type selection */}
          <ToggleGroup
            value={[goalType]}
            onValueChange={(v) => { if (v.length > 0) setGoalType(v[v.length - 1] as GoalType); }}
            className="grid grid-cols-2 gap-2"
          >
            <ToggleGroupItem value="race" className="flex-col items-start gap-1 h-auto py-3 px-4 data-[pressed]:border-primary data-[pressed]:bg-primary/10">
              <span className="font-semibold text-sm"><Trans>Race Goal</Trans></span>
              <span className="text-xs text-muted-foreground"><Trans>Train toward a specific race date</Trans></span>
            </ToggleGroupItem>
            <ToggleGroupItem value="continuous" className="flex-col items-start gap-1 h-auto py-3 px-4 data-[pressed]:border-primary data-[pressed]:bg-primary/10">
              <span className="font-semibold text-sm"><Trans>Continuous</Trans></span>
              <span className="text-xs text-muted-foreground"><Trans>Build fitness over time</Trans></span>
            </ToggleGroupItem>
          </ToggleGroup>

          {/* Distance selection */}
          <div className="space-y-2">
            <Label><Trans>Distance</Trans></Label>
            <ToggleGroup
              value={[distance]}
              onValueChange={(v) => { if (v.length > 0) setDistance(v[v.length - 1]); }}
              className="grid grid-cols-4 gap-1.5"
            >
              {DISTANCES.map((d) => (
                <ToggleGroupItem key={d.value} value={d.value} className="text-xs data-[pressed]:border-primary data-[pressed]:bg-primary/10 data-[pressed]:text-primary">
                  {d.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>

          {/* Race date */}
          {goalType === 'race' && (
            <div className="space-y-2">
              <Label htmlFor="race-date"><Trans>Race Date</Trans></Label>
              <Input
                id="race-date"
                type="date"
                value={raceDate}
                onChange={(e) => setRaceDate(e.target.value)}
              />
            </div>
          )}

          {/* Target time */}
          <div className="space-y-2">
            <Label htmlFor="target-time">
              <Trans>Target Time</Trans> <span className="text-muted-foreground"><Trans>(optional)</Trans></span>
            </Label>
            <Input
              id="target-time"
              type="text"
              value={targetTimeInput}
              onChange={(e) => setTargetTimeInput(e.target.value)}
              placeholder={selectedDist?.placeholder ?? 'H:MM:SS'}
              className="font-data"
            />
            <p className="text-[10px] text-muted-foreground">
              {goalType === 'race'
                ? t`Leave blank to track predicted time only`
                : t`What time are you working toward? Leave blank to track trend only`}
            </p>
          </div>

          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            <Trans>Cancel</Trans>
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? <Trans>Saving...</Trans> : <Trans>Save Goal</Trans>}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
