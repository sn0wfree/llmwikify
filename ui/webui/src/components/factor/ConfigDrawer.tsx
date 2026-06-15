/**
 * ConfigDrawer — right-side drawer for backtest config.
 *
 * Uses Radix Dialog with custom positioning to act as a right-side drawer.
 * Content: universe selector / adj mode / hedge / n_groups / direction / dates.
 * On "应用并重跑" — invokes onApply and closes.
 */

import {
  Dialog, DialogContent, DialogPortal, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X, Play, Settings2 } from "lucide-react";
import { Button } from "@/components/ui/legacy-button";
import { cn } from "@/lib/utils";

export interface ConfigState {
  universe: string;
  customUniverse: string;
  adjMode: string;
  hedge: string;
  nGroups: number;
  factorDirection: number;
  startDate: string;
  endDate: string;
  symbol: string;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  value: ConfigState;
  onChange: (next: ConfigState) => void;
  onApply: () => void;
  loading?: boolean;
}

const LABEL_CLASS = "text-[10px] text-muted-foreground uppercase tracking-wider mb-1";
const INPUT_CLASS = "w-full px-2.5 py-1.5 bg-muted border border-border rounded text-xs text-foreground focus:outline-none focus:border-primary transition-colors";

export function ConfigDrawer({ open, onOpenChange, value, onChange, onApply, loading }: Props) {
  const v = value;

  const update = (patch: Partial<ConfigState>) => onChange({ ...v, ...patch });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogPortal>
        <DialogPrimitive.Overlay
          className={cn(
            "fixed inset-0 z-50 bg-black/40 backdrop-blur-sm",
            "data-[state=open]:animate-in data-[state=open]:fade-in-0",
            "data-[state=closed]:animate-out data-[state=closed]:fade-out-0",
          )}
        />
        <DialogContent
          className={cn(
            "fixed right-0 top-0 bottom-0 z-50 h-full w-[28rem] max-w-[92vw]",
            "border-l border-border bg-card shadow-elevated",
            "data-[state=open]:animate-in data-[state=open]:slide-in-from-right-full",
            "data-[state=closed]:animate-out data-[state=closed]:slide-out-to-right-full",
            "duration-300 flex flex-col gap-0 p-0",
          )}
        >
          {/* Header */}
          <div className="px-5 py-4 border-b border-border flex items-center gap-2 bg-gradient-to-r from-primary/5 to-accent/5">
            <Settings2 className="w-4 h-4 text-primary" />
            <div className="flex-1 min-w-0">
              <DialogTitle className="text-sm font-semibold">回测参数</DialogTitle>
              <DialogDescription className="text-[10px] text-muted-foreground">
                修改后点击底部「应用并重跑」生效
              </DialogDescription>
            </div>
            <DialogPrimitive.Close className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded">
              <X className="w-4 h-4" />
            </DialogPrimitive.Close>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
            {/* Universe */}
            <div>
              <label className={LABEL_CLASS}>股票池</label>
              <select
                value={v.universe}
                onChange={(e) => update({ universe: e.target.value })}
                className={INPUT_CLASS}
              >
                <option value="HS300">沪深 300</option>
                <option value="ZZ500">中证 500</option>
                <option value="SZ50">上证 50</option>
                <option value="ZZ1000">中证 1000</option>
                <option value="all">全 A 股</option>
                <option value="single">单标的 (旧)</option>
                <option value="custom">自定义...</option>
              </select>
              {v.universe === "custom" && (
                <input
                  type="text"
                  value={v.customUniverse}
                  onChange={(e) => update({ customUniverse: e.target.value })}
                  className={cn(INPUT_CLASS, "mt-2 font-mono")}
                  placeholder="指数代码"
                />
              )}
              {v.universe === "single" && (
                <input
                  type="text"
                  value={v.symbol}
                  onChange={(e) => update({ symbol: e.target.value })}
                  className={cn(INPUT_CLASS, "mt-2 font-mono")}
                  placeholder="Symbol"
                />
              )}
            </div>

            {/* Rebalance / Hedge / Groups / Direction in 2-col grid */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={LABEL_CLASS}>调仓频率</label>
                <select
                  value={v.adjMode}
                  onChange={(e) => update({ adjMode: e.target.value })}
                  className={INPUT_CLASS}
                >
                  <option value="D">日频</option>
                  <option value="M-end">月频 (月末)</option>
                  <option value="W-end">周频 (周五)</option>
                </select>
              </div>
              <div>
                <label className={LABEL_CLASS}>对冲基准</label>
                <select
                  value={v.hedge}
                  onChange={(e) => update({ hedge: e.target.value })}
                  className={INPUT_CLASS}
                >
                  <option value="equal">等权</option>
                  <option value="HS300">HS300 对冲</option>
                  <option value="ZZ500">ZZ500 对冲</option>
                  <option value="SZ50">SZ50 对冲</option>
                </select>
              </div>
              <div>
                <label className={LABEL_CLASS}>分组数</label>
                <select
                  value={v.nGroups}
                  onChange={(e) => update({ nGroups: Number(e.target.value) })}
                  className={INPUT_CLASS}
                >
                  {[3, 5, 10].map((n) => (
                    <option key={n} value={n}>{n} 组</option>
                  ))}
                </select>
              </div>
              <div>
                <label className={LABEL_CLASS}>因子方向</label>
                <select
                  value={v.factorDirection}
                  onChange={(e) => update({ factorDirection: Number(e.target.value) })}
                  className={INPUT_CLASS}
                >
                  <option value={1}>越大越好 ↑</option>
                  <option value={-1}>越小越好 ↓</option>
                </select>
              </div>
            </div>

            {/* Dates */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={LABEL_CLASS}>开始日期</label>
                <input
                  type="date"
                  value={v.startDate}
                  onChange={(e) => update({ startDate: e.target.value })}
                  className={INPUT_CLASS}
                />
              </div>
              <div>
                <label className={LABEL_CLASS}>结束日期</label>
                <input
                  type="date"
                  value={v.endDate}
                  onChange={(e) => update({ endDate: e.target.value })}
                  className={INPUT_CLASS}
                />
              </div>
            </div>

            {/* Presets */}
            <div>
              <label className={LABEL_CLASS}>参数预设</label>
              <div className="grid grid-cols-3 gap-2">
                {[
                  { label: "标准", adj: "M-end", groups: 5, direction: 1 },
                  { label: "严苛", adj: "D", groups: 10, direction: 1 },
                  { label: "宽松", adj: "M-end", groups: 3, direction: 1 },
                ].map((p) => (
                  <button
                    key={p.label}
                    onClick={() => update({ adjMode: p.adj, nGroups: p.groups, factorDirection: p.direction })}
                    className="px-2 py-1.5 text-[11px] rounded border border-border bg-muted/50 hover:bg-muted hover:border-primary/30 transition-colors"
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="px-5 py-3 border-t border-border bg-card flex items-center gap-2">
            <div className="flex-1 text-[10px] text-muted-foreground">
              {v.universe} · {v.adjMode} · {v.nGroups}组
            </div>
            <Button variant="secondary" size="sm" onClick={() => onOpenChange(false)}>
              取消
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => { onApply(); onOpenChange(false); }}
              disabled={loading}
              className="shadow-soft"
            >
              {loading ? (
                <span className="animate-pulse">回测中...</span>
              ) : (
                <>
                  <Play className="w-3 h-3 mr-1" />
                  应用并重跑
                </>
              )}
            </Button>
          </div>
        </DialogContent>
      </DialogPortal>
    </Dialog>
  );
}
