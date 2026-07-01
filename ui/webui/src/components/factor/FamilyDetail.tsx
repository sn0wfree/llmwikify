/**
 * FamilyDetail — L1 族详情页: 顶部介绍 + 成员表（可排序/搜索）
 *
 * Fetches /api/factor/families/{family} + /api/factor/families/{family}/metrics
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Loader2, Search, ChevronUp, ChevronDown,
  Layers, ExternalLink,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Badge } from '../ui/legacy-badge';

interface FamilyMeta {
  slug: string;
  display_name: string;
  description: string;
  source?: { paper?: string; authors?: string[]; year?: number; url?: string };
  asset_class: string;
  category: string;
}

interface Member {
  slug: string;
  name: string;
  display_name: string;
  status: string;
  alpha_index: number | null;
  layers_present: string[];
}

interface Metrics {
  ic_mean: number | null;
  icir: number | null;
  ic_winrate: number | null;
  elapsed_sec: number | null;
}

type SortKey = 'alpha_index' | 'ic_mean' | 'icir' | 'ic_winrate';
type SortDir = 'asc' | 'desc';

const STATUS_OPTIONS = ['全部', '已验证', '已注册', '草稿', '已废弃'];
const STATUS_LABELS: Record<string, string> = {
  '已验证': '已验证',
  '已注册': '已注册',
  '草稿': '草稿',
  '已废弃': '已废弃',
};

const STATUS_VARIANT: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  '已验证': 'default',
  '已注册': 'secondary',
  '草稿': 'outline',
  '已废弃': 'destructive',
};

function LayersIndicator({ layers }: { layers: string[] }) {
  const all = ['l1', 'l2', 'l3', 'l4', 'l5', 'l6'];
  return (
    <div className="flex gap-0.5" title={`层: ${layers.join(', ')}`}>
      {all.map((l) => (
        <div
          key={l}
          className={cn(
            'w-1.5 h-1.5 rounded-full',
            layers.includes(l) ? 'bg-primary' : 'bg-muted'
          )}
          title={l.toUpperCase()}
        />
      ))}
    </div>
  );
}

export function FamilyDetail() {
  const { family } = useParams<{ family: string }>();
  const navigate = useNavigate();

  const [meta, setMeta] = useState<FamilyMeta | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [metrics, setMetrics] = useState<Record<string, Metrics>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Search & sort state
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('alpha_index');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [statusFilter, setStatusFilter] = useState('全部');

  // Load family structure
  useEffect(() => {
    if (!family) return;
    let cancelled = false;
    fetch(`/api/factor/families/${family}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => {
        if (cancelled) return;
        setMeta({
          slug: d.slug,
          display_name: d.meta?.display_name || d.slug,
          description: d.meta?.description || '',
          source: d.meta?.source,
          asset_class: d.meta?.asset_class || '',
          category: d.meta?.category || '',
        });
        setMembers(d.members || []);
      })
      .catch((e) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [family]);

  // Load metrics (all members)
  const loadMetrics = useCallback(async () => {
    if (!family || members.length === 0) return;
    try {
      const res = await fetch(`/api/factor/families/${family}/metrics`);
      if (!res.ok) return;
      const d = await res.json();
      setMetrics(d.metrics || {});
    } catch { /* ignore */ }
  }, [family, members.length]);

  useEffect(() => { loadMetrics(); }, [loadMetrics]);

  // Filter & sort
  const filtered = members
    .filter((m) => {
      if (statusFilter !== '全部' && m.status !== statusFilter) return false;
      if (!search) return true;
      const q = search.toLowerCase();
      return (
        m.display_name.toLowerCase().includes(q) ||
        m.name.toLowerCase().includes(q) ||
        String(m.alpha_index).includes(q)
      );
    })
    .sort((a, b) => {
      let va: number, vb: number;
      if (sortKey === 'alpha_index') {
        va = a.alpha_index ?? 0;
        vb = b.alpha_index ?? 0;
      } else {
        const ma = metrics[String(a.alpha_index)] || {};
        const mb = metrics[String(b.alpha_index)] || {};
        va = (ma as unknown as Record<string, number>)[sortKey] ?? 0;
        vb = (mb as unknown as Record<string, number>)[sortKey] ?? 0;
      }
      return sortDir === 'asc' ? va - vb : vb - va;
    });

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const m of members) {
      counts[m.status] = (counts[m.status] || 0) + 1;
    }
    return counts;
  }, [members]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error || !meta) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-2 text-muted-foreground">
        <p className="text-sm">{error || '族未找到'}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border bg-background/95 backdrop-blur">
        <div className="flex items-center gap-2 mb-2">
          <button
            onClick={() => navigate('/agent/factor')}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <Layers className="w-4 h-4 text-primary" />
          <h1 className="text-sm font-semibold">{meta.display_name}</h1>
          <Badge variant="outline" className="text-[10px]">
            {meta.category || 'alpha'} 族
          </Badge>
        </div>
        {meta.description && (
          <p className="text-xs text-muted-foreground">{meta.description}</p>
        )}
        {meta.source && (
          <div className="flex items-center gap-2 text-[10px] text-muted-foreground mt-1">
            {meta.source.authors && <span>{meta.source.authors.join(', ')}</span>}
            {meta.source.year && <span>· {meta.source.year}</span>}
            {meta.source.url && (
              <a href={meta.source.url} target="_blank" rel="noopener noreferrer" className="hover:text-foreground">
                <ExternalLink className="w-3 h-3 inline" />
              </a>
            )}
          </div>
        )}
        <div className="flex items-center gap-3 text-xs text-muted-foreground mt-2">
          <span>{members.length} 成员</span>
          <span>·</span>
          {Object.entries(statusCounts).map(([status, count]) => (
            <span key={status}>{STATUS_LABELS[status] || status} {count}</span>
          ))}
        </div>
      </div>

      {/* Toolbar */}
      <div className="px-6 py-2 border-b border-border flex items-center gap-3">
        <span className="text-xs font-medium text-muted-foreground">
          成员因子 ({filtered.length})
        </span>
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索..."
            className="w-full pl-7 pr-3 py-1.5 text-xs rounded border border-border bg-background focus:outline-none focus:border-primary"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="text-xs px-2 py-1.5 rounded border border-border bg-background focus:outline-none focus:border-primary"
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
        <span className="text-[11px] text-muted-foreground">
          {filtered.length} / {members.length}
        </span>
      </div>

      {/* Member table */}
      <div className="flex-1 overflow-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-background border-b border-border">
            <tr className="text-muted-foreground">
              <th className="text-left px-4 py-2 font-medium">#</th>
              <th className="text-left px-4 py-2 font-medium">名称</th>
              <th className="text-left px-4 py-2 font-medium">状态</th>
              <th
                className="text-right px-4 py-2 font-medium cursor-pointer hover:text-foreground"
                onClick={() => toggleSort('ic_mean')}
              >
                <span className="inline-flex items-center gap-0.5">
                  IC
                  {sortKey === 'ic_mean' && (sortDir === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />)}
                </span>
              </th>
              <th
                className="text-right px-4 py-2 font-medium cursor-pointer hover:text-foreground"
                onClick={() => toggleSort('icir')}
              >
                <span className="inline-flex items-center gap-0.5">
                  ICIR
                  {sortKey === 'icir' && (sortDir === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />)}
                </span>
              </th>
              <th
                className="text-right px-4 py-2 font-medium cursor-pointer hover:text-foreground"
                onClick={() => toggleSort('ic_winrate')}
              >
                <span className="inline-flex items-center gap-0.5">
                  胜率
                  {sortKey === 'ic_winrate' && (sortDir === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />)}
                </span>
              </th>
              <th className="text-center px-4 py-2 font-medium">层</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((m) => {
              const ai = m.alpha_index;
              const met = ai ? metrics[String(ai)] : undefined;
              return (
                <tr
                  key={m.slug}
                  className="border-b border-border/50 hover:bg-muted/30 cursor-pointer"
                  onClick={() => navigate(`/agent/factor/${encodeURIComponent(m.slug)}`)}
                >
                  <td className="px-4 py-2 font-mono text-muted-foreground">{ai ?? '-'}</td>
                  <td className="px-4 py-2 font-medium">{m.display_name}</td>
                  <td className="px-4 py-2">
                    <Badge variant={STATUS_VARIANT[m.status] || 'outline'} className="text-[9px] px-1 py-0">
                      {m.status}
                    </Badge>
                  </td>
                  <td className={cn('px-4 py-2 text-right font-mono', met?.ic_mean != null && met.ic_mean > 0 ? 'text-emerald-600' : met?.ic_mean != null && met.ic_mean < 0 ? 'text-rose-600' : '')}>
                    {met?.ic_mean != null ? met.ic_mean.toFixed(4) : <span className="text-muted-foreground">-</span>}
                  </td>
                  <td className={cn('px-4 py-2 text-right font-mono', met?.icir != null && met.icir > 0 ? 'text-emerald-600' : met?.icir != null && met.icir < 0 ? 'text-rose-600' : '')}>
                    {met?.icir != null ? met.icir.toFixed(4) : <span className="text-muted-foreground">-</span>}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">
                    {met?.ic_winrate != null ? `${(met.ic_winrate * 100).toFixed(1)}%` : <span className="text-muted-foreground">-</span>}
                  </td>
                  <td className="px-4 py-2 flex justify-center">
                    <LayersIndicator layers={m.layers_present} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
