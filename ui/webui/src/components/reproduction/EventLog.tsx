/**
 * EventLog — chronological event stream for a reproduction session.
 *
 * Mirrors AutoResearchPanel's EventLog style: monospace, type-tagged,
 * auto-scroll on new events.
 */

import { useEffect, useRef } from 'react';
import { cn } from '@/lib/utils';
import type { ReproductionEvent } from '../../lib/reproduction-api';

interface EventLogProps {
  events: ReproductionEvent[];
  emptyText?: string;
}

const TYPE_BG: Record<string, string> = {
  'error': 'bg-red-500/10 text-red-400',
  'done': 'bg-green-500/10 text-green-400',
  'finalize.done': 'bg-green-500/10 text-green-400',
  'backtest.done': 'bg-blue-500/10 text-primary',
  'extract.done': 'bg-blue-500/10 text-primary',
  'data.fetched': 'bg-blue-500/10 text-primary',
  'wiki.written': 'bg-purple-500/10 text-purple-400',
};

function summarize(event: ReproductionEvent): string {
  let payload: Record<string, unknown> = {};
  try { payload = JSON.parse(event.payload_json); } catch { /* noop */ }

  switch (event.event_type) {
    case 'extract.done':
      return `✓ 提取策略 — ${payload.signal_type} ${JSON.stringify(payload.params || {})}`;
    case 'data.fetched':
      return `↓ 拉取数据 — ${payload.source} (${payload.rows} 行)`;
    case 'backtest.done':
      return `✓ 回测完成 — sharpe=${payload.sharpe}, ${payload.trades} 笔交易`;
    case 'wiki.written':
      return `▤ 写入 Wiki — ${payload.slug}`;
    case 'finalize.done':
      return `✓ 完成归档`;
    case 'error':
      return `✗ ${payload.message || '失败'}`;
    default:
      return event.event_type;
  }
}

export function EventLog({ events, emptyText = '等待事件流...' }: EventLogProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events.length]);

  if (events.length === 0) {
    return (
      <div className="text-xs text-muted-foreground text-center py-8">
        {emptyText}
      </div>
    );
  }

  return (
    <div className="space-y-1 font-mono text-[11px]">
      {events.map((e) => (
        <div
          key={e.id}
          className={cn(
            'px-2 py-1.5 rounded flex items-start gap-2',
            TYPE_BG[e.event_type] || 'text-muted-foreground'
          )}
        >
          <span className="opacity-60 shrink-0">{e.event_type}</span>
          <span className="flex-1">{summarize(e)}</span>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}