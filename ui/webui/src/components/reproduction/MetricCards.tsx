/**
 * MetricCards — render BacktestResult metrics in a 2x3 grid.
 *
 * Sharpe / MDD / Win Rate / Total Return / Final Cash / Trades
 */

import { Card } from '../ui/Card';
import { TrendingUp, TrendingDown, Activity, Target, Wallet, BarChart3 } from 'lucide-react';
import type { ReproductionMetrics } from '../../lib/reproduction-api';

interface MetricCardsProps {
  metrics: ReproductionMetrics | null | undefined;
}

export function MetricCards({ metrics }: MetricCardsProps) {
  if (!metrics) {
    return (
      <Card padding="md">
        <div className="text-xs text-muted-foreground text-center py-8">
          暂无回测结果
        </div>
      </Card>
    );
  }

  const cards = [
    {
      label: 'Sharpe',
      value: metrics.sharpe_ratio.toFixed(4),
      icon: BarChart3,
      color: metrics.sharpe_ratio >= 1 ? 'text-green-400' :
             metrics.sharpe_ratio >= 0 ? 'text-yellow-400' : 'text-red-400',
      bg: metrics.sharpe_ratio >= 1 ? 'bg-green-500/10' :
          metrics.sharpe_ratio >= 0 ? 'bg-yellow-500/10' : 'bg-red-500/10',
    },
    {
      label: '最大回撤',
      value: `${(metrics.max_drawdown * 100).toFixed(2)}%`,
      icon: TrendingDown,
      color: 'text-red-400',
      bg: 'bg-red-500/10',
    },
    {
      label: '胜率',
      value: `${(metrics.win_rate * 100).toFixed(1)}%`,
      icon: Target,
      color: metrics.win_rate >= 0.5 ? 'text-green-400' : 'text-yellow-400',
      bg: metrics.win_rate >= 0.5 ? 'bg-green-500/10' : 'bg-yellow-500/10',
    },
    {
      label: '总收益',
      value: `${(metrics.total_return * 100).toFixed(2)}%`,
      icon: metrics.total_return >= 0 ? TrendingUp : TrendingDown,
      color: metrics.total_return >= 0 ? 'text-green-400' : 'text-red-400',
      bg: metrics.total_return >= 0 ? 'bg-green-500/10' : 'bg-red-500/10',
    },
    {
      label: '期末资金',
      value: metrics.final_cash.toLocaleString('zh-CN', { maximumFractionDigits: 2 }),
      icon: Wallet,
      color: 'text-primary',
      bg: 'bg-primary/10',
    },
    {
      label: '交易次数',
      value: String(metrics.trades),
      icon: Activity,
      color: 'text-foreground',
      bg: 'bg-muted',
    },
  ];

  return (
    <div className="grid grid-cols-3 gap-3">
      {cards.map(({ label, value, icon: Icon, color, bg }) => (
        <div
          key={label}
          className="bg-card border border-border rounded-lg p-3 transition-all hover:border-primary/30"
        >
          <div className="flex items-start justify-between mb-2">
            <div className="text-[11px] text-muted-foreground">{label}</div>
            <div className={`w-7 h-7 rounded-md ${bg} flex items-center justify-center`}>
              <Icon className={`w-3.5 h-3.5 ${color}`} />
            </div>
          </div>
          <div className={`text-xl font-semibold tabular-nums ${color}`}>
            {value}
          </div>
        </div>
      ))}
    </div>
  );
}