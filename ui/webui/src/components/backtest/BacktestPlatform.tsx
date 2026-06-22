/**
 * BacktestPlatform — single-factor backtest + strategy backtest.
 *
 * Two tabs:
 *   1. 单因子回测: FactorPanel content (left sidebar + 4-tab results)
 *   2. 策略回测: StrategyPanel content (left sidebar + KPI/PnL)
 *
 * Wraps existing FactorPanel and StrategyPanel via lazy loading.
 */

import { useState } from 'react';
import { Beaker, TrendingUp, Activity } from 'lucide-react';
import { cn } from '@/lib/utils';
import { FactorPanel } from '../factor/FactorPanel';
import { StrategyPanel } from '../strategy/StrategyPanel';

// ─── Types ──────────────────────────────────────────────────

type TabId = 'factor' | 'strategy';

const TABS: { id: TabId; label: string; icon: typeof Beaker }[] = [
  { id: 'factor', label: '单因子回测', icon: Beaker },
  { id: 'strategy', label: '策略回测', icon: TrendingUp },
];

// ─── Component ──────────────────────────────────────────────

export function BacktestPlatform() {
  const [activeTab, setActiveTab] = useState<TabId>('factor');

  return (
    <div className="flex flex-col h-full">
      {/* Tab bar */}
      <div className="flex gap-1 px-4 py-2 border-b border-border bg-card">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors',
                activeTab === tab.id
                  ? 'bg-primary/10 text-foreground font-medium'
                  : 'text-muted-foreground hover:bg-white/[0.04] hover:text-foreground',
              )}
            >
              <Icon className="w-3.5 h-3.5" />
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Content */}
      <div className="flex-1 min-h-0">
        {activeTab === 'factor' && <FactorPanel />}
        {activeTab === 'strategy' && <StrategyPanel />}
      </div>
    </div>
  );
}
