/**
 * AutoResearchDetail — 6-Step Framework Result Visualization (v5)
 *
 * Renders the 6 step result panels (Step 1-6) for a given session.
 * Pure SVG visualizations: radar chart (Step 3) + bar chart (Step 4).
 * No external chart library — keeps the bundle slim.
 */
import {
  type AutoResearchSession,
  type AutoResearchSixStepFields,
  type SixStepClarification,
  type SixStepReasoning,
  type SixStepStructure,
} from '../lib/autoresearch-api';

const REASONING_DIMS = [
  { key: 'conclusion_evidence_alignment', label: '结论-证据' },
  { key: 'logical_contradiction',         label: '逻辑矛盾' },
  { key: 'causal_coverage',              label: '因果覆盖' },
  { key: 'premise_evidence_alignment',   label: '前提-证据' },
  { key: 'assumption_visibility',        label: '假设显式' },
  { key: 'uncertainty_quantification',   label: '不确定性' },
] as const;

const STRUCTURE_LAYERS = [
  { key: 'hierarchical_support',  label: '层级支撑' },
  { key: 'section_completeness',  label: '章节完整' },
  { key: 'internal_consistency',  label: '内部一致' },
] as const;

const STEP_COLORS: Record<number, string> = {
  1: 'border-blue-500/30 bg-blue-500/5',
  2: 'border-green-500/30 bg-green-500/5',
  3: 'border-purple-500/30 bg-purple-500/5',
  4: 'border-orange-500/30 bg-orange-500/5',
  5: 'border-slate-500/30 bg-slate-500/5',
  6: 'border-cyan-500/30 bg-cyan-500/5',
};

const STEP_ACCENTS: Record<number, string> = {
  1: 'text-blue-400',
  2: 'text-green-400',
  3: 'text-purple-400',
  4: 'text-orange-400',
  5: 'text-slate-400',
  6: 'text-cyan-400',
};

function PanelShell({
  step,
  title,
  status,
  children,
}: {
  step: number;
  title: string;
  status: 'present' | 'missing' | 'partial';
  children: React.ReactNode;
}) {
  return (
    <div className={`p-3 border rounded-lg ${STEP_COLORS[step]}`}>
      <div className="flex items-center justify-between mb-2">
        <div className={`text-sm font-bold ${STEP_ACCENTS[step]}`}>
          ⑥ {step}. {title}
        </div>
        <div
          className={`text-[10px] px-1.5 py-0.5 rounded ${
            status === 'present'
              ? 'bg-green-500/20 text-green-400'
              : status === 'partial'
              ? 'bg-yellow-500/20 text-yellow-400'
              : 'bg-slate-500/20 text-slate-400'
          }`}
        >
          {status === 'present' ? '✓ 已完成' : status === 'partial' ? '部分' : '未运行'}
        </div>
      </div>
      {children}
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="text-xs text-[var(--text-secondary)] italic py-3 text-center">
      {message}
    </div>
  );
}

// ─── Step 1: Concept Clarification ───────────────────────────

function Step1Panel({ data }: { data: SixStepClarification | null }) {
  if (!data) {
    return (
      <PanelShell step={1} title="概念澄清" status="missing">
        <EmptyState message="该步骤未运行（或无数据）" />
      </PanelShell>
    );
  }
  return (
    <PanelShell step={1} title="概念澄清" status="present">
      {data.context && (
        <div className="mb-2">
          <div className="text-[10px] text-[var(--text-secondary)] mb-0.5">语境</div>
          <div className="text-xs text-[var(--text-primary)] leading-relaxed">{data.context}</div>
        </div>
      )}
      {data.boundaries && (
        <div className="mb-2">
          <div className="text-[10px] text-[var(--text-secondary)] mb-0.5">边界</div>
          <div className="text-xs text-[var(--text-primary)] leading-relaxed">{data.boundaries}</div>
        </div>
      )}
      {data.position && (
        <div className="mb-2">
          <div className="text-[10px] text-[var(--text-secondary)] mb-0.5">视角</div>
          <div className="text-xs text-[var(--text-primary)]">{data.position}</div>
        </div>
      )}
      {Array.isArray(data.premises) && data.premises.length > 0 && (
        <div className="mb-2">
          <div className="text-[10px] text-[var(--text-secondary)] mb-1">前提</div>
          <ul className="text-xs text-[var(--text-primary)] space-y-0.5 list-disc list-inside">
            {data.premises.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        </div>
      )}
      {data.scope_check !== undefined && (
        <div className="mt-2 flex items-center gap-2 text-[10px]">
          <span className="text-[var(--text-secondary)]">scope_check:</span>
          <span className={data.scope_check ? 'text-green-400' : 'text-red-400'}>
            {data.scope_check ? '✓ true' : '✗ false'}
          </span>
        </div>
      )}
    </PanelShell>
  );
}

// ─── Step 2: Evidence Scoring ────────────────────────────────

function Step2Panel({
  data,
  sourceCount,
}: {
  data: Record<string, number> | null;
  sourceCount: number;
}) {
  if (!data || Object.keys(data).length === 0) {
    return (
      <PanelShell step={2} title="建立依据" status="missing">
        <EmptyState message="该步骤未运行（或无数据）" />
      </PanelShell>
    );
  }
  const values = Object.values(data);
  const avg = values.reduce((a, b) => a + b, 0) / values.length;
  const min = Math.min(...values);
  const max = Math.max(...values);
  return (
    <PanelShell step={2} title="建立依据" status="present">
      <div className="text-xs text-[var(--text-primary)] mb-2">
        <span className="text-[var(--text-secondary)]">{Object.keys(data).length} sources scored</span>
        <span className="mx-2 text-[var(--text-secondary)]">·</span>
        <span>avg <span className="font-mono font-bold">{avg.toFixed(3)}</span></span>
        <span className="mx-2 text-[var(--text-secondary)]">·</span>
        <span>min <span className="font-mono text-red-400">{min.toFixed(2)}</span></span>
        <span className="mx-2 text-[var(--text-secondary)]">·</span>
        <span>max <span className="font-mono text-green-400">{max.toFixed(2)}</span></span>
      </div>
      <div className="text-[10px] text-[var(--text-secondary)] mb-2">
        vs session sources: {sourceCount}
        {Object.keys(data).length !== sourceCount && (
          <span className="text-yellow-400 ml-1">⚠ count mismatch</span>
        )}
      </div>
      <div className="space-y-1 max-h-40 overflow-y-auto">
        {Object.entries(data)
          .sort(([, a], [, b]) => b - a)
          .slice(0, 10)
          .map(([sid, score]) => (
            <div key={sid} className="flex items-center gap-2 text-[10px]">
              <span className="font-mono text-[var(--text-secondary)] w-20 truncate">
                {sid.slice(0, 8)}
              </span>
              <div className="flex-1 h-1.5 bg-[var(--bg-tertiary)] rounded overflow-hidden">
                <div
                  className={`h-full ${
                    score >= 0.7 ? 'bg-green-500' : score >= 0.5 ? 'bg-yellow-500' : 'bg-red-500'
                  }`}
                  style={{ width: `${Math.min(100, score * 100)}%` }}
                />
              </div>
              <span
                className={`font-mono w-10 text-right ${
                  score >= 0.7 ? 'text-green-400' : score >= 0.5 ? 'text-yellow-400' : 'text-red-400'
                }`}
              >
                {score.toFixed(2)}
              </span>
            </div>
          ))}
        {Object.keys(data).length > 10 && (
          <div className="text-[10px] text-[var(--text-secondary)] text-center">
            ... +{Object.keys(data).length - 10} more
          </div>
        )}
      </div>
    </PanelShell>
  );
}

// ─── Step 3: Reasoning (radar chart) ─────────────────────────

function RadarChart({ scores }: { scores: Record<string, number> }) {
  const size = 160;
  const cx = size / 2;
  const cy = size / 2;
  const radius = 60;
  const n = REASONING_DIMS.length;
  const angleStep = (Math.PI * 2) / n;

  // Compute polygon points for data
  const points = REASONING_DIMS.map((d, i) => {
    const angle = -Math.PI / 2 + i * angleStep;
    const r = (scores[d.key] ?? 0) * radius;
    return [cx + Math.cos(angle) * r, cy + Math.sin(angle) * r];
  });
  const polygon = points.map(([x, y]) => `${x},${y}`).join(' ');

  // Concentric reference rings (0.25 / 0.5 / 0.75 / 1.0)
  const rings = [0.25, 0.5, 0.75, 1.0].map((scale) => {
    const ringPoints = Array.from({ length: n }, (_, i) => {
      const angle = -Math.PI / 2 + i * angleStep;
      const r = scale * radius;
      return `${cx + Math.cos(angle) * r},${cy + Math.sin(angle) * r}`;
    }).join(' ');
    return (
      <polygon
        key={scale}
        points={ringPoints}
        fill="none"
        stroke="currentColor"
        strokeOpacity={0.15}
        strokeWidth={0.5}
      />
    );
  });

  return (
    <svg width={size} height={size} className="text-purple-400">
      {rings}
      {/* Axis lines */}
      {REASONING_DIMS.map((_, i) => {
        const angle = -Math.PI / 2 + i * angleStep;
        return (
          <line
            key={i}
            x1={cx}
            y1={cy}
            x2={cx + Math.cos(angle) * radius}
            y2={cy + Math.sin(angle) * radius}
            stroke="currentColor"
            strokeOpacity={0.2}
            strokeWidth={0.5}
          />
        );
      })}
      {/* Data polygon */}
      <polygon
        points={polygon}
        fill="currentColor"
        fillOpacity={0.2}
        stroke="currentColor"
        strokeWidth={1.5}
      />
      {/* Data points */}
      {points.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={2} fill="currentColor" />
      ))}
    </svg>
  );
}

function Step3Panel({ data }: { data: SixStepReasoning | null }) {
  if (!data) {
    return (
      <PanelShell step={3} title="推理严密" status="missing">
        <EmptyState message="该步骤未运行（或无数据）" />
      </PanelShell>
    );
  }
  const aggPct = (data.aggregate_score * 100).toFixed(0);
  return (
    <PanelShell step={3} title="推理严密" status="present">
      <div className="flex flex-col sm:flex-row gap-3 items-start">
        <div className="shrink-0 self-center sm:self-start">
          <RadarChart scores={data.scores} />
        </div>
        <div className="flex-1 min-w-0 w-full">
          <div className="flex items-baseline gap-2 mb-2">
            <div className={`text-2xl font-bold ${STEP_ACCENTS[3]}`}>{aggPct}%</div>
            <div className="text-[10px] text-[var(--text-secondary)]">
              aggregate ({data.method || 'rule_based'})
            </div>
          </div>
          <div className="space-y-0.5 mb-2">
            {REASONING_DIMS.map((d) => {
              const v = data.scores[d.key] ?? 0;
              return (
                <div key={d.key} className="flex items-center gap-2 text-[10px]">
                  <span className="w-20 text-[var(--text-secondary)]">{d.label}</span>
                  <div className="flex-1 h-1 bg-[var(--bg-tertiary)] rounded overflow-hidden">
                    <div
                      className={`h-full ${v >= 0.7 ? 'bg-green-500' : v >= 0.5 ? 'bg-yellow-500' : 'bg-red-500'}`}
                      style={{ width: `${v * 100}%` }}
                    />
                  </div>
                  <span className="font-mono w-8 text-right text-[var(--text-primary)]">
                    {v.toFixed(2)}
                  </span>
                </div>
              );
            })}
          </div>
          {data.issues && data.issues.length > 0 && (
            <details className="text-[10px]">
              <summary className="cursor-pointer text-[var(--text-secondary)]">
                {data.issues.length} issues
              </summary>
              <ul className="mt-1 space-y-0.5 text-[var(--text-primary)]">
                {data.issues.map((it, i) => (
                  <li key={i} className="text-[10px]">
                    <span className={it.severity === 'warning' ? 'text-yellow-400' : 'text-slate-400'}>
                      [{it.severity}]
                    </span>{' '}
                    {it.message}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      </div>
    </PanelShell>
  );
}

// ─── Step 4: Structure (bar chart) ──────────────────────────

function BarChart({ scores }: { scores: Record<string, number> }) {
  return (
    <div className="space-y-1">
      {STRUCTURE_LAYERS.map((l) => {
        const v = scores[l.key] ?? 0;
        return (
          <div key={l.key} className="flex items-center gap-2 text-[10px]">
            <span className="w-16 text-[var(--text-secondary)]">{l.label}</span>
            <div className="flex-1 h-3 bg-[var(--bg-tertiary)] rounded overflow-hidden relative">
              <div
                className={`h-full ${v >= 0.7 ? 'bg-orange-500' : v >= 0.5 ? 'bg-yellow-500' : 'bg-red-500'}`}
                style={{ width: `${v * 100}%` }}
              />
            </div>
            <span className="font-mono w-10 text-right text-[var(--text-primary)]">
              {v.toFixed(2)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function Step4Panel({ data }: { data: SixStepStructure | null }) {
  if (!data) {
    return (
      <PanelShell step={4} title="稳固结构" status="missing">
        <EmptyState message="该步骤未运行（或无数据）" />
      </PanelShell>
    );
  }
  const aggPct = (data.aggregate_score * 100).toFixed(0);
  return (
    <PanelShell step={4} title="稳固结构" status="present">
      <div className="flex items-baseline gap-2 mb-2">
        <div className={`text-2xl font-bold ${STEP_ACCENTS[4]}`}>{aggPct}%</div>
        <div className="text-[10px] text-[var(--text-secondary)]">
          aggregate ({data.method || 'rule_based'})
        </div>
      </div>
      <BarChart scores={data.scores} />
      {data.issues && data.issues.length > 0 && (
        <details className="text-[10px] mt-2">
          <summary className="cursor-pointer text-[var(--text-secondary)]">
            {data.issues.length} issues
          </summary>
          <ul className="mt-1 space-y-0.5 text-[var(--text-primary)]">
            {data.issues.map((it, i) => (
              <li key={i} className="text-[10px]">
                <span className={it.severity === 'warning' ? 'text-yellow-400' : 'text-slate-400'}>
                  [{it.severity}]
                </span>{' '}
                {it.message}
              </li>
            ))}
          </ul>
        </details>
      )}
    </PanelShell>
  );
}

// ─── Step 5: Report (link) ──────────────────────────────────

function Step5Panel({
  hasReport,
  hasReview,
}: {
  hasReport: boolean;
  hasReview: boolean;
}) {
  return (
    <PanelShell step={5} title="结论输出" status={hasReport ? 'present' : 'missing'}>
      {hasReport ? (
        <div className="text-xs text-[var(--text-primary)]">
          ✓ 报告已生成。前往 <span className="text-[var(--accent)] font-bold">报告 tab</span> 查看。
        </div>
      ) : hasReview ? (
        <div className="text-xs text-[var(--text-secondary)]">
          报告生成中（review 阶段）
        </div>
      ) : (
        <EmptyState message="报告尚未生成" />
      )}
    </PanelShell>
  );
}

// ─── Step 6: Framework Compliance ───────────────────────────

function Step6Panel({
  hasClarification,
  hasReasoning,
  hasStructure,
  hasReport,
}: {
  hasClarification: boolean;
  hasReasoning: boolean;
  hasStructure: boolean;
  hasReport: boolean;
}) {
  const checks = [
    { key: 'clarification', label: '① 概念澄清', ok: hasClarification },
    { key: 'reasoning',     label: '③ 推理严密', ok: hasReasoning },
    { key: 'structure',     label: '④ 稳固结构', ok: hasStructure },
    { key: 'report',        label: '⑤ 结论输出', ok: hasReport },
  ];
  const passed = checks.every(c => c.ok);
  return (
    <PanelShell step={6} title="检查清单" status={passed ? 'present' : 'partial'}>
      <div className="space-y-1">
        {checks.map((c) => (
          <div key={c.key} className="flex items-center gap-2 text-xs">
            <span className={c.ok ? 'text-green-400' : 'text-slate-500'}>
              {c.ok ? '✓' : '○'}
            </span>
            <span className="text-[var(--text-primary)]">{c.label}</span>
          </div>
        ))}
      </div>
      <div className="mt-2 text-[10px]">
        {passed ? (
          <span className="text-green-400">✓ framework_compliance: all steps present</span>
        ) : (
          <span className="text-yellow-400">⚠ 部分步骤未完成</span>
        )}
      </div>
    </PanelShell>
  );
}

// ─── Main component ──────────────────────────────────────────

export function AutoResearchDetail({
  sixStep,
  session,
}: {
  sixStep: AutoResearchSixStepFields;
  session: AutoResearchSession;
}) {
  const sources = session.sources || [];
  const hasReport = !!(session.result || session.review_json);

  return (
    <div className="space-y-3 min-w-0">
      <Step1Panel data={sixStep.clarification} />
      <Step2Panel data={sixStep.evidence_scores} sourceCount={sources.length} />
      <Step3Panel data={sixStep.reasoning} />
      <Step4Panel data={sixStep.structure} />
      <Step5Panel hasReport={hasReport} hasReview={!!session.review_json} />
      <Step6Panel
        hasClarification={!!sixStep.clarification}
        hasReasoning={!!sixStep.reasoning}
        hasStructure={!!sixStep.structure}
        hasReport={hasReport}
      />
    </div>
  );
}
