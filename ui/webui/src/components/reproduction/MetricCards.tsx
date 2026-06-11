/**
 * MetricCards — render BacktestResult metrics using shared MetricCards.
 *
 * Wraps shared/MetricCards with ReproductionMetrics → Metric[] mapping.
 */

import { TrendingUp, TrendingDown, Activity, Target, Wallet, BarChart3 } from 'lucide-react';
import { MetricCards as SharedMetricCards } from '../shared/MetricCards';
import type { Metric } from '../shared/MetricCards';
import type { ReproductionMetrics } from '../../lib/reproduction-api';

interface MetricCardsProps {
  metrics: ReproductionMetrics | null | undefined;
}

export function MetricCards({ metrics }: MetricCardsProps) {
  if (!metrics) {
    return (
      <div className="text-xs text-muted-foreground text-center py-8">
        暂无回测结果
      </div>
    );
  }

  const items: Metric[] = [
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

  return <SharedMetricCards metrics={items} columns={3} />;
}
