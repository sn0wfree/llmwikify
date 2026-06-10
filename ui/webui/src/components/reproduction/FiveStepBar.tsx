/**
 * FiveStepBar — 5-phase pipeline progress visualization.
 *
 * Matches AutoResearchPanel's MiniSixStepBar pattern:
 *   - past: completed (checkmark, muted color)
 *   - current: pulsing, primary color
 *   - future: muted border
 */

import { cn } from '@/lib/utils';
import { FIVE_PHASES } from '../../lib/reproduction-api';

interface FiveStepBarProps {
  currentPhase: string | null;
  status: string;
  compact?: boolean;
}

export function FiveStepBar({ currentPhase, status, compact = false }: FiveStepBarProps) {
  let activeIdx = FIVE_PHASES.findIndex(p => p.key === currentPhase);
  if (activeIdx < 0) {
    if (status === 'done') activeIdx = FIVE_PHASES.length;
    else if (status === 'error') activeIdx = -1;
  }

  const size = compact ? 20 : 28;

  return (
    <div className="flex items-center gap-1">
      {FIVE_PHASES.map((step, idx) => {
        const isCompleted = activeIdx > idx || status === 'done';
        const isCurrent = activeIdx === idx && status !== 'done';
        const isFailed = status === 'error' && activeIdx === idx;
        return (
          <div key={step.key} className="flex items-center" title={`${step.num}. ${step.label}`}>
            <div className="relative">
              {isCurrent && (
                <div className={cn(
                  'absolute inset-0 rounded-full bg-primary/30 animate-stage-pulse'
                )} />
              )}
              <div
                className={cn(
                  'relative rounded-full flex items-center justify-center font-bold transition-all',
                  compact ? 'text-[8px]' : 'text-[10px]',
                  isCompleted && 'bg-primary/40 text-primary',
                  isCurrent && 'bg-primary text-white ring-2 ring-primary/30',
                  isFailed && 'bg-destructive/40 text-destructive',
                  !isCompleted && !isCurrent && !isFailed &&
                    'bg-muted text-muted-foreground opacity-30 border border-border'
                )}
                style={{ width: size, height: size }}
              >
                {isCompleted ? '✓' : isFailed ? '✗' : step.num}
              </div>
            </div>
            {idx < FIVE_PHASES.length - 1 && (
              <div
                className={cn(
                  compact ? 'w-2 h-px' : 'w-3 h-px',
                  isCompleted ? 'bg-primary/40' : 'bg-border'
                )}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}