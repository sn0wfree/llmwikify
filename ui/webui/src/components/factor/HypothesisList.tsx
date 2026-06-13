/**
 * HypothesisList — L4 hypothesis cards with status badges.
 */

import { CheckCircle2, XCircle, Clock, HelpCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Badge } from '../ui/badge';

interface Hypothesis {
  id?: string;
  name?: string;
  description?: string;
  expected_ic_sign?: string;
  source?: string;
  priority?: string;
  status?: string;
}

const STATUS_ICON: Record<string, typeof CheckCircle2> = {
  '未验证': Clock,
  '支持': CheckCircle2,
  '不支持': XCircle,
  '部分支持': HelpCircle,
};

const STATUS_COLOR: Record<string, string> = {
  '未验证': 'text-muted-foreground',
  '支持': 'text-emerald-500',
  '不支持': 'text-rose-500',
  '部分支持': 'text-amber-500',
};

export function HypothesisList({ hypotheses }: { hypotheses?: Hypothesis[] }) {
  if (!hypotheses || hypotheses.length === 0) {
    return (
      <div className="text-sm text-muted-foreground py-4">
        暂无假设
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-muted-foreground mb-3">假设列表</h3>
      {hypotheses.map((h, i) => {
        const Icon = STATUS_ICON[h.status || '未验证'] || HelpCircle;
        const iconColor = STATUS_COLOR[h.status || '未验证'] || 'text-muted-foreground';
        return (
          <div
            key={h.id || i}
            className="flex items-start gap-3 p-3 bg-muted/50 rounded-md border"
          >
            <Icon className={cn('w-4 h-4 mt-0.5 shrink-0', iconColor)} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-sm font-medium">
                  {h.id && <span className="font-mono text-muted-foreground mr-1">{h.id}</span>}
                  {h.name}
                </span>
                {h.priority && (
                  <Badge variant="outline" className="text-[10px]">
                    {h.priority}
                  </Badge>
                )}
              </div>
              <p className="text-xs text-muted-foreground">{h.description}</p>
              <div className="flex items-center gap-3 mt-2 text-[10px] text-muted-foreground">
                {h.expected_ic_sign && (
                  <span>预期 IC: <strong>{h.expected_ic_sign}</strong></span>
                )}
                {h.source && <span>来源: {h.source}</span>}
              </div>
            </div>
            <Badge
              variant={
                h.status === '支持' ? 'default'
                  : h.status === '不支持' ? 'destructive'
                    : 'secondary'
              }
              className="shrink-0 text-[10px]"
            >
              {h.status || '未验证'}
            </Badge>
          </div>
        );
      })}
    </div>
  );
}
