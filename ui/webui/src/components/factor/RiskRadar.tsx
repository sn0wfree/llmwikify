/**
 * RiskRadar — L6 risk visualization.
 *
 * Shows window sensitivity, regime sensitivity, decay analysis,
 * and style exposure as structured cards.
 */

import { AlertTriangle, Clock, TrendingDown, Shield } from 'lucide-react';
import { cn } from '@/lib/utils';

interface RiskData {
  window_sensitivity?: Record<string, number>;
  regime_sensitivity?: Record<string, string>;
  style_exposure?: Record<string, number>;
  decay_analysis?: Record<string, string>;
}

export function RiskRadar({ data }: { data: RiskData }) {
  return (
    <div className="space-y-4">
      {/* Window Sensitivity */}
      {data.window_sensitivity && Object.keys(data.window_sensitivity).length > 0 && (
        <RiskCard title="窗口敏感度" icon={Clock}>
          <div className="flex gap-2 flex-wrap">
            {Object.entries(data.window_sensitivity).map(([window, value]) => (
              <div
                key={window}
                className="flex flex-col items-center p-2 bg-background rounded border min-w-[60px]"
              >
                <span className="text-[10px] text-muted-foreground">{window}</span>
                <span className={cn(
                  'text-sm font-mono font-medium',
                  (value as number) > 0 ? 'text-emerald-500' : (value as number) < 0 ? 'text-rose-500' : 'text-muted-foreground',
                )}>
                  {(value as number) > 0 ? '+' : ''}{(value as number).toFixed(3)}
                </span>
              </div>
            ))}
          </div>
        </RiskCard>
      )}

      {/* Regime Sensitivity */}
      {data.regime_sensitivity && Object.keys(data.regime_sensitivity).length > 0 && (
        <RiskCard title="市场环境敏感度" icon={TrendingDown}>
          <div className="flex gap-2 flex-wrap">
            {Object.entries(data.regime_sensitivity).map(([regime, effectiveness]) => {
              const eff = effectiveness as string;
              const color = eff === '有效'
                ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
                : eff === '失效'
                  ? 'bg-rose-500/10 text-rose-500 border-rose-500/20'
                  : 'bg-muted text-muted-foreground';
              return (
                <div
                  key={regime}
                  className={cn('px-3 py-1.5 rounded-md border text-xs font-medium', color)}
                >
                  {regime}: {eff}
                </div>
              );
            })}
          </div>
        </RiskCard>
      )}

      {/* Decay Analysis */}
      {data.decay_analysis && Object.keys(data.decay_analysis).length > 0 && (
        <RiskCard title="衰减分析" icon={AlertTriangle}>
          <div className="flex gap-2 flex-wrap">
            {Object.entries(data.decay_analysis).map(([period, status]) => {
              const s = status as string;
              const color = s === '有效'
                ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
                : s === '衰减'
                  ? 'bg-amber-500/10 text-amber-500 border-amber-500/20'
                  : s === '失效'
                    ? 'bg-rose-500/10 text-rose-500 border-rose-500/20'
                    : 'bg-muted text-muted-foreground';
              return (
                <div
                  key={period}
                  className={cn('px-3 py-1.5 rounded-md border text-xs font-medium', color)}
                >
                  {period}: {s}
                </div>
              );
            })}
          </div>
        </RiskCard>
      )}

      {/* Style Exposure */}
      {data.style_exposure && Object.keys(data.style_exposure).length > 0 && (
        <RiskCard title="风格暴露" icon={Shield}>
          <div className="grid grid-cols-3 gap-2">
            {Object.entries(data.style_exposure).map(([style, exposure]) => {
              const exp = exposure as number;
              const absExp = Math.abs(exp);
              const width = Math.min(absExp * 100, 100);
              return (
                <div key={style} className="space-y-1">
                  <div className="flex items-center justify-between text-[10px]">
                    <span className="text-muted-foreground">{style}</span>
                    <span className="font-mono">{exp.toFixed(1)}</span>
                  </div>
                  <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                    <div
                      className={cn(
                        'h-full rounded-full',
                        exp > 0 ? 'bg-primary' : 'bg-rose-500',
                      )}
                      style={{ width: `${width}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </RiskCard>
      )}
    </div>
  );
}

function RiskCard({ title, icon: Icon, children }: {
  title: string;
  icon: typeof AlertTriangle;
  children: React.ReactNode;
}) {
  return (
    <div className="p-3 bg-muted/30 rounded-md border">
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-3.5 h-3.5 text-muted-foreground" />
        <h4 className="text-xs font-medium text-muted-foreground">{title}</h4>
      </div>
      {children}
    </div>
  );
}
