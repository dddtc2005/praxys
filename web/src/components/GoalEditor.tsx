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

const DISTANCES = [
  { value: '5k', label: '5K', placeholder: 'e.g. 20:00' },
  { value: '10k', label: '10K', placeholder: 'e.g. 42:00' },
  { value: 'half', label: 'Half', placeholder: 'e.g. 1:30:00' },
  { value: 'marathon', label: 'Marathon', placeholder: 'e.g. 3:00:00' },
  { value: '50k', label: '50K', placeholder: 'e.g. 4:30:00' },
  { value: '50mi', label: '50 Mi', placeholder: 'e.g. 8:00:00' },
  { value: '100k', label: '100K', placeholder: 'e.g. 12:00:00' },
  { value: '100mi', label: '100 Mi', placeholder: 'e.g. 24:00:00' },
];

function formatTime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function parseTimeToSeconds(input: string): number | null {
  const trimmed = input.trim();
  if (!trimmed) return null;
  const parts = trimmed.split(':').map(Number);
  if (parts.some(isNaN)) return null;
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 2) return parts[0] * 3600 + parts[1] * 60;
  if (parts.length === 1 && parts[0] > 0) return parts[0];
  return null;
}

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
  const [goalType, setGoalType] = useState<GoalType>(initialType);
  const [raceDate, setRaceDate] = useState(initialRaceDate);
  const [distance, setDistance] = useState(initialDistance || 'marathon');
  const [targetTimeInput, setTargetTimeInput] = useState(
    initialTargetTime ? formatTime(initialTargetTime) : ''
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const selectedDist = DISTANCES.find((d) => d.value === distance);

  const handleSave = async () => {
    setError('');

    if (goalType === 'race' && !raceDate) {
      setError('Race date is required');
      return;
    }

    const targetTimeSec = parseTimeToSeconds(targetTimeInput);
    if (targetTimeInput.trim() && targetTimeSec === null) {
      setError('Invalid time format. Use H:MM:SS or H:MM');
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
    } catch {
      setError('Failed to save goal');
    }
    setSaving(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Set Your Goal</DialogTitle>
          <DialogDescription>
            Choose a race target or track continuous improvement.
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
              <span className="font-semibold text-sm">Race Goal</span>
              <span className="text-xs text-muted-foreground">Train toward a specific race date</span>
            </ToggleGroupItem>
            <ToggleGroupItem value="continuous" className="flex-col items-start gap-1 h-auto py-3 px-4 data-[pressed]:border-primary data-[pressed]:bg-primary/10">
              <span className="font-semibold text-sm">Continuous</span>
              <span className="text-xs text-muted-foreground">Build fitness over time</span>
            </ToggleGroupItem>
          </ToggleGroup>

          {/* Distance selection */}
          <div className="space-y-2">
            <Label>Distance</Label>
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
              <Label htmlFor="race-date">Race Date</Label>
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
              Target Time <span className="text-muted-foreground">(optional)</span>
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
                ? 'Leave blank to track predicted time only'
                : 'What time are you working toward? Leave blank to track trend only'}
            </p>
          </div>

          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? 'Saving...' : 'Save Goal'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
