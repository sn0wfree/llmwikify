/**
 * FactorDetail — 6-layer factor detail page.
 *
 * Displays the full 6-layer YAML content for a factor:
 *   L1: Logic (definition, formula, params)
 *   L2: Calculation (steps, edge cases, code location)
 *   L3: Financial Understanding (intuition, theory)
 *   L4: Meaning (hypotheses, insights, uncertainty)
 *   L5: Validation (IC, groups, returns, score)
 *   L6: Risk (sensitivity, exposure, failure conditions)
 */

import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Beaker, CheckCircle2, XCircle, AlertTriangle,
  Loader2, BookOpen, Calculator, TrendingUp, HelpCircle,
  BarChart3, Shield, ChevronRight, RefreshCw,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Badge } from '../ui/badge';
import { Button } from '../ui/Button';
import { HypothesisList } from './HypothesisList';
import { OverallAssessment } from './OverallAssessment';
import { RiskRadar } from './RiskRadar';
import { ICChart } from '../shared/ICChart';
import { GroupReturnBar } from '../shared/GroupReturnBar';

// ─── Types ──────────────────────────────────────────────────

type LayerId = 'l1' | 'l2' | 'l3' | 'l4' | 'l5' | 'l6';

interface FactorData {
  factor: {
    name: string;
    name_cn?: string;
    asset_type?: string;
    category?: string;
    subcategory?: string;
    version?: number;
    status?: string;
    l1?: Record<string, unknown>;
    l2?: Record<string, unknown>;
    l3?: Record<string, unknown>;
    l4?: Record<string, unknown>;
    l5?: Record<string, unknown>;
    l6?: Record<string, unknown>;
    [key: string]: unknown;
  };
}

// ─── Tab Config ─────────────────────────────────────────────

const LAYERS: { id: LayerId; label: string; icon: typeof BookOpen; color: string }[] = [
  { id: 'l1', label: 'L1 逻辑', icon: BookOpen, color: 'text-blue-500' },
  { id: 'l2', label: 'L2 计算', icon: Calculator, color: 'text-purple-500' },
  { id: 'l3', label: 'L3 金融', icon: TrendingUp, color: 'text-emerald-500' },
  { id: 'l4', label: 'L4 含义', icon: HelpCircle, color: 'text-amber-500' },
  { id: 'l5', label: 'L5 验证', icon: BarChart3, color: 'text-rose-500' },
  { id: 'l6', label: 'L6 风险', icon: Shield, color: 'text-cyan-500' },
];

const STATUS_CONFIG: Record<string, { variant: 'default' | 'secondary' | 'destructive' | 'outline'; label: string }> = {
  '已注册': { variant: 'secondary', label: '已注册' },
  '待验证': { variant: 'outline', label: '待验证' },
  '已通过': { variant: 'default', label: '已通过' },
  '失败': { variant: 'destructive', label: '失败' },
};

// ─── Component ──────────────────────────────────────────────

export function FactorDetail() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const [factor, setFactor] = useState<FactorData['factor'] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeLayer, setActiveLayer] = useState<LayerId>('l1');

  useEffect(() => {
    if (!name) return;
    setLoading(true);
    setError(null);
    fetch(`/api/factor/library/${encodeURIComponent(name)}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => setFactor(data.factor))
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

  if (error || !factor) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <XCircle className="w-12 h-12 text-destructive" />
        <p className="text-muted-foreground">{error || 'Factor not found'}</p>
        <Button variant="ghost" onClick={() => navigate(-1)}>
          <ArrowLeft className="w-4 h-4 mr-2" /> Go Back
        </Button>
      </div>
    );
  }

  const l1 = factor.l1 as Record<string, unknown> | undefined;
  const l2 = factor.l2 as Record<string, unknown> | undefined;
  const l3 = factor.l3 as Record<string, unknown> | undefined;
  const l4 = factor.l4 as Record<string, unknown> | undefined;
  const l5 = factor.l5 as Record<string, unknown> | undefined;
  const l6 = factor.l6 as Record<string, unknown> | undefined;

  const statusConf = STATUS_CONFIG[factor.status || '已注册'] || STATUS_CONFIG['已注册'];

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
          <Beaker className="w-5 h-5 text-primary shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-semibold truncate">
                {factor.name_cn || factor.name}
              </h1>
              <Badge variant={statusConf.variant} className="shrink-0">
                {statusConf.label}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground truncate">
              {l1?.definition as string || factor.name}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {factor.asset_type && (
              <Badge variant="outline" className="text-xs">
                {factor.asset_type}
              </Badge>
            )}
            {factor.category && (
              <Badge variant="outline" className="text-xs">
                {factor.category}
              </Badge>
            )}
            {factor.version && (
              <span className="text-xs text-muted-foreground">v{factor.version}</span>
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
        {activeLayer === 'l1' && <L1Content data={l1} />}
        {activeLayer === 'l2' && <L2Content data={l2} />}
        {activeLayer === 'l3' && <L3Content data={l3} />}
        {activeLayer === 'l4' && <L4Content data={l4} />}
        {activeLayer === 'l5' && <L5Content data={l5} factorName={factor.name} />}
        {activeLayer === 'l6' && <L6Content data={l6} />}
      </div>
    </div>
  );
}

// ─── L1: Logic Layer ────────────────────────────────────────

function L1Content({ data }: { data: Record<string, unknown> | undefined }) {
  if (!data) return <EmptyLayer />;

  return (
    <div className="space-y-6 max-w-3xl">
      <Section title="因子定义">
        <p className="text-sm">{str(data.definition)}</p>
      </Section>

      <Section title="数学公式">
        <code className="block p-3 bg-muted rounded-md text-sm font-mono">
          {str(data.formula)}
        </code>
      </Section>

      <div className="grid grid-cols-2 gap-4">
        <Section title="输入列">
          <code className="text-sm">{JSON.stringify(data.input_columns)}</code>
        </Section>
        <Section title="数据频率">
          <span className="text-sm">{str(data.frequency)}</span>
        </Section>
        <Section title="输出 Schema">
          <code className="text-sm">{str(data.output_schema)}</code>
        </Section>
        <Section title="NaN 含义">
          <span className="text-sm">{str(data.nan_meaning)}</span>
        </Section>
      </div>

      <Section title="默认参数">
        <code className="text-sm">{JSON.stringify(data.default_params)}</code>
      </Section>

      <Section title="参数约束">
        <code className="text-sm">{JSON.stringify(data.param_constraints)}</code>
      </Section>

      <Section title="业务约束">
        <p className="text-sm">{str(data.business_constraints)}</p>
      </Section>
    </div>
  );
}

// ─── L2: Calculation Layer ──────────────────────────────────

function L2Content({ data }: { data: Record<string, unknown> | undefined }) {
  if (!data) return <EmptyLayer />;

  const steps = data.calculation_steps as Array<Record<string, unknown>> | undefined;

  return (
    <div className="space-y-6 max-w-3xl">
      {steps && steps.length > 0 && (
        <Section title="计算步骤">
          <div className="space-y-3">
            {steps.map((step, i) => (
              <div key={i} className="flex gap-3 p-3 bg-muted rounded-md">
                <div className="flex items-center justify-center w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-bold shrink-0">
                  {step.step as number}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium">{str(step.description)}</p>
                  {str(step.formula) && (
                    <code className="block mt-1 text-xs text-muted-foreground font-mono">
                      {str(step.formula)}
                    </code>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      <div className="grid grid-cols-2 gap-4">
        <Section title="边界处理">
          <span className="text-sm">{str(data.edge_case_handling)}</span>
        </Section>
        <Section title="缺失值处理">
          <span className="text-sm">{str(data.missing_value_handling)}</span>
        </Section>
        <Section title="数据对齐">
          <span className="text-sm">{str(data.data_alignment)}</span>
        </Section>
        <Section title="计算复杂度">
          <code className="text-sm">{str(data.complexity)}</code>
        </Section>
      </div>

      {str(data.code_location) && (
        <Section title="代码位置">
          <code className="text-sm">{str(data.code_location)}</code>
        </Section>
      )}
    </div>
  );
}

// ─── L3: Financial Understanding ────────────────────────────

function L3Content({ data }: { data: Record<string, unknown> | undefined }) {
  if (!data) return <EmptyLayer />;

  return (
    <div className="space-y-6 max-w-3xl">
      <Section title="金融直觉">
        <p className="text-sm">{str(data.financial_intuition)}</p>
      </Section>
      <Section title="市场行为刻画">
        <p className="text-sm">{str(data.market_behavior)}</p>
      </Section>
      <Section title="理论基础">
        <p className="text-sm">{str(data.theoretical_basis)}</p>
      </Section>
      <Section title="历史有效性">
        <p className="text-sm">{str(data.historical_effectiveness)}</p>
      </Section>
      <Section title="与同类因子的关系">
        <p className="text-sm">{str(data.related_factors)}</p>
      </Section>
    </div>
  );
}

// ─── L4: Meaning Layer ──────────────────────────────────────

function L4Content({ data }: { data: Record<string, unknown> | undefined }) {
  if (!data) return <EmptyLayer />;

  return (
    <div className="space-y-6 max-w-3xl">
      <HypothesisList hypotheses={data.hypotheses as Array<Record<string, unknown>>} />

      <Section title="因子含义总结">
        <p className="text-sm whitespace-pre-wrap">{str(data.meaning_summary)}</p>
      </Section>

      {data.key_insights != null && (
        <Section title="关键洞察">
          <ul className="space-y-1">
            {(data.key_insights as string[]).map((insight, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <ChevronRight className="w-4 h-4 text-primary shrink-0 mt-0.5" />
                {insight}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="不确定性">
        <p className="text-sm whitespace-pre-wrap text-muted-foreground">
          {str(data.uncertainty)}
        </p>
      </Section>

      {str(data.final_meaning) && (
        <Section title="验证后含义">
          <p className="text-sm font-medium text-primary">{str(data.final_meaning)}</p>
        </Section>
      )}
    </div>
  );
}

// ─── L5: Validation Layer ───────────────────────────────────

interface BacktestRun {
  run_id: string;
  created_at: string;
  status: string;
  universe: string;
  start_date: string;
  end_date: string;
  metrics: {
    ic_mean: number;
    rank_ic_mean: number;
    icir: number;
    rank_icir: number;
    win_rate: number;
    annual_return: number;
    longshort_ann_return: number;
    longshort_sharpe: number;
    longshort_max_dd: number;
  };
  ic_series: Array<{ date: string; ic: number; rank_ic?: number; n_stocks?: number }>;
  group_metrics: Record<string, { annual_return: number; sharpe?: number }>;
}

function L5Content({ data, factorName }: { data: Record<string, unknown> | undefined; factorName?: string }) {
  const [backtestRuns, setBacktestRuns] = useState<BacktestRun[]>([]);
  const [btLoading, setBtLoading] = useState(false);
  const [btError, setBtError] = useState<string | null>(null);

  const fetchBacktest = () => {
    if (!factorName) return;
    setBtLoading(true);
    setBtError(null);
    fetch(`/api/factor/${encodeURIComponent(factorName)}/backtest?limit=5`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => setBacktestRuns(d.runs || []))
      .catch((e) => setBtError(e.message))
      .finally(() => setBtLoading(false));
  };

  useEffect(() => { fetchBacktest(); }, [factorName]);

  const assessment = data?.overall_assessment as Record<string, unknown> | undefined;
  const hypothesisTesting = data?.hypothesis_testing as Array<Record<string, unknown>> | undefined;
  const latestRun = backtestRuns[0];

  return (
    <div className="space-y-6 max-w-3xl">
      {assessment && <OverallAssessment assessment={assessment} />}

      {/* Backtest Charts */}
      <Section title="回测结果">
        {btLoading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="w-4 h-4 animate-spin" /> 加载回测数据...
          </div>
        )}
        {btError && (
          <p className="text-sm text-destructive">{btError}</p>
        )}
        {!btLoading && !btError && backtestRuns.length === 0 && (
          <div className="text-sm text-muted-foreground">
            暂无回测结果。
            <Button variant="ghost" size="sm" className="ml-2" onClick={fetchBacktest}>
              <RefreshCw className="w-3 h-3 mr-1" /> 重试
            </Button>
          </div>
        )}
        {latestRun && (
          <div className="space-y-4">
            {/* Metrics Summary */}
            <div className="grid grid-cols-4 gap-3">
              <MetricCard label="IC Mean" value={latestRun.metrics.ic_mean.toFixed(4)} />
              <MetricCard label="ICIR" value={latestRun.metrics.icir.toFixed(4)} />
              <MetricCard label="Rank IC" value={latestRun.metrics.rank_ic_mean.toFixed(4)} />
              <MetricCard label="Win Rate" value={`${(latestRun.metrics.win_rate * 100).toFixed(1)}%`} />
              <MetricCard label="年化收益" value={`${(latestRun.metrics.annual_return * 100).toFixed(1)}%`} />
              <MetricCard label="多空年化" value={`${(latestRun.metrics.longshort_ann_return * 100).toFixed(1)}%`} />
              <MetricCard label="多空Sharpe" value={latestRun.metrics.longshort_sharpe.toFixed(2)} />
              <MetricCard label="多空MaxDD" value={`${(latestRun.metrics.longshort_max_dd * 100).toFixed(1)}%`} />
            </div>

            {/* IC Time Series */}
            {latestRun.ic_series.length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-muted-foreground mb-2">IC 时序</h4>
                <ICChart icSeries={latestRun.ic_series} height={280} />
              </div>
            )}

            {/* Group Returns */}
            {Object.keys(latestRun.group_metrics).length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-muted-foreground mb-2">分组年化收益</h4>
                <GroupReturnBar
                  groups={Object.fromEntries(
                    Object.entries(latestRun.group_metrics).map(([k, v]) => [k, v.annual_return])
                  )}
                  height={160}
                />
              </div>
            )}

            <p className="text-xs text-muted-foreground">
              数据区间: {latestRun.start_date} → {latestRun.end_date} | 宇宙: {latestRun.universe} | {latestRun.created_at}
            </p>
          </div>
        )}
      </Section>

      {hypothesisTesting && (
        <Section title="假设检验结果">
          <div className="space-y-2">
            {hypothesisTesting.map((ht, i) => (
              <div key={i} className="flex items-center justify-between p-3 bg-muted rounded-md">
                <span className="text-sm font-mono">{str(ht.hypothesis_id)}</span>
                <Badge
                  variant={
                    ht.conclusion === '支持'
                      ? 'default'
                      : ht.conclusion === '不支持（反向）'
                        ? 'destructive'
                        : 'secondary'
                  }
                >
                  {str(ht.conclusion)}
                </Badge>
              </div>
            ))}
          </div>
        </Section>
      )}

      {str(data?.validation_date) && (
        <Section title="验证日期">
          <span className="text-sm text-muted-foreground">{str(data?.validation_date)}</span>
        </Section>
      )}
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-2 bg-muted rounded-md">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-sm font-mono font-medium">{value}</div>
    </div>
  );
}

// ─── L6: Risk Layer ─────────────────────────────────────────

function L6Content({ data }: { data: Record<string, unknown> | undefined }) {
  if (!data) return <EmptyLayer />;

  return (
    <div className="space-y-6 max-w-3xl">
      <RiskRadar data={data} />

      <div className="grid grid-cols-2 gap-4">
        <Section title="行业集中度">
          <span className="text-sm">{str(data.industry_concentration)}</span>
        </Section>
        <Section title="拥挤度">
          <span className="text-sm">{str(data.crowding_level)}</span>
        </Section>
      </div>

      {str(data.failure_conditions) && (
        <Section title="失效条件">
          <p className="text-sm">{str(data.failure_conditions)}</p>
        </Section>
      )}

      {str(data.risk_notes) && (
        <Section title="风险说明">
          <p className="text-sm">{str(data.risk_notes)}</p>
        </Section>
      )}
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
