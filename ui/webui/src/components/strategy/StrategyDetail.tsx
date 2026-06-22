/**
 * StrategyDetail — strategy definition detail page.
 *
 * Displays the strategy YAML content:
 *   L1: Strategy Logic (definition, signal_type, rebalance_freq)
 *   L2: Calculation (signal generation, position sizing)
 *   L3: Financial Understanding (market regime, risk factors)
 *   L4: Meaning (hypotheses, expected behavior)
 *
 * Adapted from FactorDetail.tsx for strategy definitions.
 */

import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, TrendingUp, AlertTriangle,
  Loader2, BookOpen, Calculator, HelpCircle,
  ChevronRight,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Badge } from '../ui/legacy-badge';
import { Button } from '../ui/legacy-button';

// ─── Types ──────────────────────────────────────────────────

type LayerId = 'l1' | 'l2' | 'l3' | 'l4';

interface StrategyData {
  strategy: {
    name: string;
    name_cn?: string;
    strategy_class?: string;
    signal_type?: string;
    signal_params?: Record<string, unknown>;
    factor_refs?: string[];
    rebalance_freq?: string;
    status?: string;
    l1?: Record<string, unknown>;
    l2?: Record<string, unknown>;
    l3?: Record<string, unknown>;
    l4?: Record<string, unknown>;
    [key: string]: unknown;
  };
}

// ─── Tab Config ─────────────────────────────────────────────

const LAYERS: { id: LayerId; label: string; icon: typeof BookOpen; color: string }[] = [
  { id: 'l1', label: 'L1 逻辑', icon: BookOpen, color: 'text-blue-500' },
  { id: 'l2', label: 'L2 计算', icon: Calculator, color: 'text-purple-500' },
  { id: 'l3', label: 'L3 金融', icon: TrendingUp, color: 'text-emerald-500' },
  { id: 'l4', label: 'L4 含义', icon: HelpCircle, color: 'text-amber-500' },
];

const STATUS_CONFIG: Record<string, { variant: 'default' | 'secondary' | 'destructive' | 'outline'; label: string }> = {
  '已注册': { variant: 'secondary', label: '已注册' },
  'draft': { variant: 'outline', label: 'Draft' },
  'backtested': { variant: 'secondary', label: 'Backtested' },
  'validated': { variant: 'default', label: 'Validated' },
  'deprecated': { variant: 'destructive', label: 'Deprecated' },
};

// ─── Component ──────────────────────────────────────────────

export function StrategyDetail() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const [strategy, setStrategy] = useState<StrategyData['strategy'] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeLayer, setActiveLayer] = useState<LayerId>('l1');

  useEffect(() => {
    if (!name) return;
    setLoading(true);
    setError(null);
    fetch(`/api/strategy/${encodeURIComponent(name)}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => setStrategy(data.strategy))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [name]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error || !strategy) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <AlertTriangle className="w-12 h-12 text-destructive" />
        <p className="text-muted-foreground">{error || 'Strategy not found'}</p>
        <Button variant="ghost" onClick={() => navigate(-1)}>
          <ArrowLeft className="w-4 h-4 mr-2" /> Go Back
        </Button>
      </div>
    );
  }

  const l1 = strategy.l1 as Record<string, unknown> | undefined;
  const l2 = strategy.l2 as Record<string, unknown> | undefined;
  const l3 = strategy.l3 as Record<string, unknown> | undefined;
  const l4 = strategy.l4 as Record<string, unknown> | undefined;

  const statusConf = STATUS_CONFIG[strategy.status || '已注册'] || STATUS_CONFIG['已注册'];

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="flex items-center gap-3 px-6 py-4">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate(-1)}
            className="shrink-0"
          >
            <ArrowLeft className="w-4 h-4" />
          </Button>
          <TrendingUp className="w-5 h-5 text-primary shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-semibold truncate">
                {strategy.name_cn || strategy.name}
              </h1>
              <Badge variant={statusConf.variant} className="shrink-0">
                {statusConf.label}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground truncate">
              {l1?.definition as string || strategy.name}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {strategy.strategy_class && (
              <Badge variant="outline" className="text-xs">
                {strategy.strategy_class}
              </Badge>
            )}
            {strategy.signal_type && (
              <Badge variant="outline" className="text-xs">
                {strategy.signal_type}
              </Badge>
            )}
          </div>
        </div>

        {/* Layer Tabs */}
        <div className="flex gap-1 px-6 pb-2">
          {LAYERS.map((layer) => {
            const Icon = layer.icon;
            return (
              <button
                key={layer.id}
                onClick={() => setActiveLayer(layer.id)}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors',
                  activeLayer === layer.id
                    ? 'bg-primary/10 text-foreground font-medium'
                    : 'text-muted-foreground hover:bg-white/[0.04] hover:text-foreground',
                )}
              >
                <Icon className={cn('w-3.5 h-3.5', layer.color)} />
                {layer.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-6">
        {activeLayer === 'l1' && <L1Content data={l1} strategy={strategy} />}
        {activeLayer === 'l2' && <L2Content data={l2} />}
        {activeLayer === 'l3' && <L3Content data={l3} />}
        {activeLayer === 'l4' && <L4Content data={l4} />}
      </div>
    </div>
  );
}

// ─── L1: Strategy Logic ─────────────────────────────────────

function L1Content({ data, strategy }: { data: Record<string, unknown> | undefined; strategy: StrategyData['strategy'] }) {
  if (!data) return <EmptyLayer />;

  return (
    <div className="space-y-6 max-w-3xl">
      <Section title="策略定义">
        <p className="text-sm">{str(data.definition)}</p>
      </Section>

      <div className="grid grid-cols-2 gap-4">
        <Section title="信号类型">
          <span className="text-sm">{str(strategy.signal_type)}</span>
        </Section>
        <Section title="策略类型">
          <span className="text-sm">{str(strategy.strategy_class)}</span>
        </Section>
        <Section title="调仓频率">
          <span className="text-sm">{str(strategy.rebalance_freq)}</span>
        </Section>
        <Section title="因子引用">
          <code className="text-sm">{JSON.stringify(strategy.factor_refs)}</code>
        </Section>
      </div>

      <Section title="信号参数">
        <code className="text-sm">{JSON.stringify(strategy.signal_params)}</code>
      </Section>
    </div>
  );
}

// ─── L2: Calculation ────────────────────────────────────────

function L2Content({ data }: { data: Record<string, unknown> | undefined }) {
  if (!data) return <EmptyLayer />;

  return (
    <div className="space-y-6 max-w-3xl">
      <Section title="信号生成">
        <p className="text-sm">{str(data.signal_generation)}</p>
      </Section>
      <Section title="仓位管理">
        <p className="text-sm">{str(data.position_sizing)}</p>
      </Section>
      <Section title="交易执行">
        <p className="text-sm">{str(data.execution)}</p>
      </Section>
    </div>
  );
}

// ─── L3: Financial Understanding ────────────────────────────

function L3Content({ data }: { data: Record<string, unknown> | undefined }) {
  if (!data) return <EmptyLayer />;

  return (
    <div className="space-y-6 max-w-3xl">
      <Section title="市场环境">
        <p className="text-sm">{str(data.market_regime)}</p>
      </Section>
      <Section title="风险因素">
        <p className="text-sm">{str(data.risk_factors)}</p>
      </Section>
      <Section title="理论基础">
        <p className="text-sm">{str(data.theoretical_basis)}</p>
      </Section>
    </div>
  );
}

// ─── L4: Meaning ────────────────────────────────────────────

function L4Content({ data }: { data: Record<string, unknown> | undefined }) {
  if (!data) return <EmptyLayer />;

  return (
    <div className="space-y-6 max-w-3xl">
      <Section title="策略含义">
        <p className="text-sm">{str(data.meaning)}</p>
      </Section>
      <Section title="预期行为">
        <p className="text-sm">{str(data.expected_behavior)}</p>
      </Section>
      <Section title="不确定性">
        <p className="text-sm">{str(data.uncertainty)}</p>
      </Section>
    </div>
  );
}

// ─── Shared Components ──────────────────────────────────────

function str(v: unknown): string {
  return v == null ? '' : String(v);
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-sm font-medium text-muted-foreground mb-2">{title}</h3>
      {children}
    </div>
  );
}

function EmptyLayer() {
  return (
    <div className="flex flex-col items-center justify-center h-32 text-muted-foreground">
      <AlertTriangle className="w-8 h-8 mb-2 opacity-50" />
      <p className="text-sm">该层数据尚未填充</p>
    </div>
  );
}
