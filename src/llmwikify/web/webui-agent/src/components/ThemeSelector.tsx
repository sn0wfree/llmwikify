/**
 * PPT Generator - Theme Selector Component
 *
 * v0.6.1: 36 themes grouped by category with search box.
 * Each theme card shows a small CSS-gradient preview swatch.
 *
 * Themes adapted from html-ppt-skill
 * (https://github.com/lewislulu/html-ppt-skill, MIT, 5.4k ⭐).
 */

import React, { useMemo, useState } from 'react';
import {
  Theme,
  THEMES,
  ThemeCategory,
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  searchThemes,
  getThemesByCategory,
} from '../lib/ppt-themes';

interface ThemeSelectorProps {
  selectedTheme: string;
  onSelect: (themeId: string) => void;
}

function ThemeSwatch({ theme }: { theme: Theme }) {
  // Use 3-color swatch: primary, accent, bg
  return (
    <div className="flex gap-1 mb-1.5">
      <span
        className="w-4 h-4"
        style={{ background: theme.tokens['color-accent'] || theme.colors.primary, borderRadius: 'var(--radius-sm, 4px)' }}
      />
      <span
        className="w-4 h-4"
        style={{ background: theme.tokens['color-accent-2'] || theme.colors.secondary, borderRadius: 'var(--radius-sm, 4px)' }}
      />
      <span
        className="w-4 h-4"
        style={{
          background: theme.tokens['color-bg'] || theme.colors.background,
          border: '1px solid var(--color-border, rgba(0,0,0,.1))',
          borderRadius: 'var(--radius-sm, 4px)',
        }}
      />
    </div>
  );
}

function ThemeCard({
  theme,
  selected,
  onClick,
}: {
  theme: Theme;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`relative p-2 text-left transition-all ${
        selected
          ? 'ring-2 ring-blue-500 bg-blue-50'
          : 'hover:bg-gray-50 border border-gray-200 hover:border-gray-300'
      }`}
      style={{ borderRadius: '8px' }}
      title={theme.description}
    >
      <ThemeSwatch theme={theme} />
      <div className="text-xs font-medium truncate" style={{ color: 'var(--color-text-1, #0a0a0a)' }}>
        {theme.name_zh}
      </div>
      <div className="text-[10px] text-gray-500 truncate">
        {theme.name_en}
      </div>
    </button>
  );
}

export function ThemeSelector({ selectedTheme, onSelect }: ThemeSelectorProps) {
  const [query, setQuery] = useState('');
  const [collapsed, setCollapsed] = useState<Set<ThemeCategory>>(new Set());

  const filtered = useMemo(() => searchThemes(query), [query]);

  const grouped = useMemo(() => {
    const g: Partial<Record<ThemeCategory, Theme[]>> = {};
    for (const theme of filtered) {
      if (!g[theme.category]) g[theme.category] = [];
      g[theme.category]!.push(theme);
    }
    return g;
  }, [filtered]);

  const toggleCategory = (cat: ThemeCategory) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  };

  // If searching, show flat grid
  if (query.trim()) {
    return (
      <div className="bg-white rounded-lg shadow-md p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold">主题 · {filtered.length}</h3>
        </div>
        <input
          type="text"
          placeholder="搜索主题名/分类/描述..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full px-3 py-1.5 mb-3 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        {filtered.length === 0 ? (
          <div className="text-sm text-gray-500 text-center py-8">未找到匹配主题</div>
        ) : (
          <div className="grid grid-cols-4 gap-2 max-h-96 overflow-y-auto">
            {filtered.map((t) => (
              <ThemeCard
                key={t.id}
                theme={t}
                selected={selectedTheme === t.id}
                onClick={() => onSelect(t.id)}
              />
            ))}
          </div>
        )}
      </div>
    );
  }

  // Default grouped display
  return (
    <div className="bg-white rounded-lg shadow-md p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-semibold">主题 · {THEMES.length}</h3>
        <span className="text-xs text-gray-500">点击切换</span>
      </div>
      <input
        type="text"
        placeholder="搜索主题..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        className="w-full px-3 py-1.5 mb-3 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      <div className="space-y-3 max-h-[28rem] overflow-y-auto pr-1">
        {CATEGORY_ORDER.map((cat) => {
          const themes = grouped[cat];
          if (!themes || themes.length === 0) return null;
          const isCollapsed = collapsed.has(cat);
          return (
            <div key={cat}>
              <button
                onClick={() => toggleCategory(cat)}
                className="w-full flex items-center justify-between text-sm font-semibold text-gray-700 mb-1.5"
              >
                <span>
                  {CATEGORY_LABELS[cat].zh}{' '}
                  <span className="text-xs text-gray-400 font-normal">/ {CATEGORY_LABELS[cat].en}</span>
                  <span className="text-xs text-gray-400 font-normal ml-1">· {themes.length}</span>
                </span>
                <span className="text-xs">{isCollapsed ? '▶' : '▼'}</span>
              </button>
              {!isCollapsed && (
                <div className="grid grid-cols-4 gap-2">
                  {themes.map((t) => (
                    <ThemeCard
                      key={t.id}
                      theme={t}
                      selected={selectedTheme === t.id}
                      onClick={() => onSelect(t.id)}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="mt-3 pt-2 border-t border-gray-100 text-[10px] text-gray-400 text-center">
        Themes adapted from{' '}
        <a
          href="https://github.com/lewislulu/html-ppt-skill"
          target="_blank"
          rel="noreferrer"
          className="underline hover:text-gray-600"
        >
          html-ppt-skill
        </a>{' '}
        (MIT, © 2026 lewislulu)
      </div>
    </div>
  );
}

export default ThemeSelector;
