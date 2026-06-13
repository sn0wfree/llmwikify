/**
 * OverallAssessment — L5 factor score + status + final meaning.
 */

import { CheckCircle2, XCircle, Clock, TrendingUp } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Badge } from '../ui/badge';

interface Assessment {
  score?: number;
  status?: string;
  pass_threshold?: number;
  final_meaning?: string;
}

const STATUS_CONFIG: Record<string, { icon: typeof CheckCircle2; color: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }> = {
  '通过': { icon: CheckCircle2, color: 'text-emerald-500', variant: 'default' },
  '失败': { icon: XCircle, color: 'text-rose-500', variant: 'destructive' },
  '待更新': { icon: Clock, color: 'text-muted-foreground', variant: 'secondary' },
  '待验证': { icon: Clock, color: 'text-muted-foreground', variant: 'secondary' },
};

function getScoreColor(score: number, threshold: number): string {
  if (score >= threshold) return 'text-emerald-500';
  if (score >= threshold * 0.7) return 'text-amber-500';
  return 'text-rose-500';
}

function getScoreBg(score: number, threshold: number): string {
  if (score >= threshold) return 'bg-emerald-500';
  if (score >= threshold * 0.7) return 'bg-amber-500';
  return 'bg-rose-500';
}

export function OverallAssessment({ assessment }: { assessment: Assessment }) {
  const score = assessment.score ?? 0;
  const threshold = assessment.pass_threshold ?? 60;
  const status = assessment.status || '待验证';
  const conf = STATUS_CONFIG[status] || STATUS_CONFIG['待验证'];
  const Icon = conf.icon;

  return (
    <div className="p-4 bg-muted/30 rounded-lg border">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium">综合评估</h3>
        <Badge variant={conf.variant} className="flex items-center gap-1">
          <Icon className={cn('w-3 h-3', conf.color)} />
          {status}
        </Badge>
      </div>

      {/* Score Bar */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-1">
          <span className="text-2xl font-bold tabular-nums">{score}</span>
          <span className="text-xs text-muted-foreground">/ 100（通过线: {threshold}）</span>
        </div>
        <div className="h-2 bg-muted rounded-full overflow-hidden">
          <div
            className={cn('h-full rounded-full transition-all', getScoreBg(score, threshold))}
            style={{ width: `${Math.min(score, 100)}%` }}
          />
        </div>
      </div>

      {/* Final Meaning */}
      {assessment.final_meaning && (
        <div className="p-3 bg-background rounded-md border">
          <div className="flex items-center gap-2 mb-1">
            <TrendingUp className="w-3.5 h-3.5 text-primary" />
            <span className="text-xs font-medium text-muted-foreground">验证后含义</span>
          </div>
          <p className="text-sm">{assessment.final_meaning}</p>
        </div>
      )}
    </div>
  );
}
