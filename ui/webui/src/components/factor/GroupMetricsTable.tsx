/**
 * GroupMetricsTable — per-group quantile metrics table.
 *
 * Columns: 分组 | 年化 | Sharpe | 最大回撤 | 月胜率 | 换手率 | 持仓数
 * Last row: 多空 (G1 - G5) — highlighted with top border.
 *
 * Direction: 1 = long top (G_n), -1 = long bottom (G_1).
 * Colors: positive → emerald-500, negative → rose-500.
 */

import { TrendingDown, TrendingUp, Minus } from "lucide-react";
import { posNegColor } from "@/lib/posNegColor";

interface GroupMetric {
  sharpe: number;
  max_drawdown: number;
  win_rate: number;
  turnover: number;
  n_stocks: number;
}

interface LongShortMetric {
  ann_return: number;
  sharpe: number;
  mdd: number;
  win_rate: number;
  turnover: number;
}

interface Props {
  groupMetrics: Record<string, GroupMetric>;
  groupReturns: Record<string, number>;
  direction: 1 | -1;
  longshort?: LongShortMetric;
}

function fmtPct(v: number, digits = 1): string {
  if (!Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

function fmtNum(v: number, digits = 2): string {
  if (!Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

function DirIcon({ g, nGroups, direction }: { g: number; nGroups: number; direction: 1 | -1 }) {
  const isLong = (direction === 1 && g === nGroups) || (direction === -1 && g === 1);
  if (isLong) {
    return direction === 1
      ? <TrendingUp className="w-3 h-3 text-emerald-500" />
      : <TrendingUp className="w-3 h-3 text-emerald-500 rotate-180" />;
  }
  if (g === 1 || g === nGroups) {
    return direction === 1
      ? <TrendingDown className="w-3 h-3 text-rose-500" />
      : <TrendingDown className="w-3 h-3 text-rose-500 rotate-180" />;
  }
  return <Minus className="w-3 h-3 text-muted-foreground" />;
}

export function GroupMetricsTable({ groupMetrics, groupReturns, direction, longshort }: Props) {
  const groupKeys = Object.keys(groupMetrics).sort();
  if (groupKeys.length === 0) {
    return (
      <div className="text-xs text-muted-foreground text-center py-6">
        无分组数据
      </div>
    );
  }
  const nGroups = groupKeys.length;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border text-muted-foreground">
            <th className="text-left py-2 pr-3 font-medium">分组</th>
            <th className="text-right py-2 px-2 font-medium">年化</th>
            <th className="text-right py-2 px-2 font-medium">Sharpe</th>
            <th className="text-right py-2 px-2 font-medium">最大回撤</th>
            <th className="text-right py-2 px-2 font-medium">月胜率</th>
            <th className="text-right py-2 px-2 font-medium">换手率</th>
            <th className="text-right py-2 pl-2 font-medium">持仓数</th>
          </tr>
        </thead>
        <tbody>
          {groupKeys.map((gl) => {
            const m = groupMetrics[gl];
            const gNum = parseInt(gl.slice(1), 10);
            const annRet = groupReturns[gl] ?? 0;
            return (
              <tr key={gl} className="border-b border-border/50 hover:bg-muted/30 transition-colors">
                <td className="py-2 pr-3 flex items-center gap-1.5">
                  <DirIcon g={gNum} nGroups={nGroups} direction={direction} />
                  <span className="font-mono font-medium">{gl}</span>
                  <span className="text-muted-foreground text-[10px]">
                    {gNum === 1 ? "bottom" : gNum === nGroups ? "top" : "mid"}
                  </span>
                </td>
                <td className={`text-right py-2 px-2 tabular-nums font-medium ${posNegColor(annRet)}`}>
                  {fmtPct(annRet)}
                </td>
                <td className={`text-right py-2 px-2 tabular-nums ${posNegColor(m.sharpe)}`}>
                  {fmtNum(m.sharpe)}
                </td>
                <td className={`text-right py-2 px-2 tabular-nums ${posNegColor(m.max_drawdown, { invert: true })}`}>
                  {fmtPct(m.max_drawdown)}
                </td>
                <td className={`text-right py-2 px-2 tabular-nums ${posNegColor(m.win_rate)}`}>
                  {fmtPct(m.win_rate)}
                </td>
                <td className="text-right py-2 px-2 tabular-nums text-muted-foreground">
                  {fmtPct(m.turnover)}
                </td>
                <td className="text-right py-2 pl-2 tabular-nums text-muted-foreground">
                  {m.n_stocks}
                </td>
              </tr>
            );
          })}

          {longshort && (
            <tr className="border-t-2 border-border bg-muted/20 font-semibold">
              <td className="py-2 pr-3 flex items-center gap-1.5">
                <Zap className="w-3 h-3 text-amber-500" />
                <span>多空 (G1 - G{nGroups})</span>
              </td>
              <td className={`text-right py-2 px-2 tabular-nums ${posNegColor(longshort.ann_return)}`}>
                {fmtPct(longshort.ann_return)}
              </td>
              <td className={`text-right py-2 px-2 tabular-nums ${posNegColor(longshort.sharpe)}`}>
                {fmtNum(longshort.sharpe)}
              </td>
              <td className={`text-right py-2 px-2 tabular-nums ${posNegColor(longshort.mdd, { invert: true })}`}>
                {fmtPct(longshort.mdd)}
              </td>
              <td className={`text-right py-2 px-2 tabular-nums ${posNegColor(longshort.win_rate)}`}>
                {fmtPct(longshort.win_rate)}
              </td>
              <td className="text-right py-2 px-2 tabular-nums text-muted-foreground">
                {fmtPct(longshort.turnover)}
              </td>
              <td className="text-right py-2 pl-2 text-muted-foreground">—</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Zap(props: { className?: string }) {
  return (
    <svg
      className={props.className}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="currentColor"
    >
      <path d="M13 2L3 14h7l-1 8 10-12h-7l1-8z" />
    </svg>
  );
}
