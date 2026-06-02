/**
 * PPT Generator - Theme Selector Component
 *
 * v0.6.2: Compact pill row + drawer.
 *
 * Default view: a single row of 6 featured theme pills + a "Show all 36 ▾"
 * toggle. Selecting a pill immediately switches theme. The drawer expands
 * below to show all 36 themes grouped by category, plus the search box.
 *
 * Themes adapted from html-ppt-skill
 * (https://github.com/lewislulu/html-ppt-skill, MIT, 5.4k ⭐).
 */

import React, { useMemo, useState } from 'react';
import {
  Theme,
  ThemeCategory,
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  LEGACY_ALIASES,
  getFeaturedThemes,
  searchThemes,
  THEMES,
} from '../lib/ppt-themes';

interface ThemeSelectorProps {
  selectedTheme: string;
  onSelect: (themeId: string) => void;
}

/**
 * Resolve a theme id (handles v0.5 legacy aliases) and return the canonical
 * Theme object. Used to decide whether the current selection is in the
 * featured pill row.
 */
function resolveThemeId(id: string): string {
  if (THEMES.some((t) => t.id === id)) return id;
  if (LEGACY_ALIASES[id]) return LEGACY_ALIASES[id];
  return THEMES[0].id;
}

// =============================================================================
// Sub-components
// =============================================================================

/**
 * Compact pill (~50×24px): color swatch dot + Chinese name.
 * Used in the default collapsed row of 6 featured themes.
 */
function ThemePill({
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
      title={`${theme.name_zh} / ${theme.name_en}\n${theme.description}`}
      className={`flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium transition-all whitespace-nowrap ${
        selected
          ? 'bg-blue-50 text-blue-700 ring-1 ring-blue-400'
          : 'bg-white text-gray-700 border border-gray-200 hover:border-gray-400 hover:bg-gray-50'
      }`}
      style={{ borderRadius: '999px' }}
    >
      <span
        className="w-2.5 h-2.5 flex-shrink-0"
        style={{
          background: theme.tokens['color-accent'] || theme.colors.primary,
          borderRadius: '50%',
        }}
      />
      <span className="truncate max-w-[5rem]">{theme.name_zh}</span>
    </button>
  );
}

/**
 * Larger chip card (~80×60px) used inside the drawer: 3-color swatch +
 * Chinese name + English name. Selected state shows a blue ring.
 */
function ThemeChipCard({
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
      title={theme.description}
      className={`relative p-2 text-left transition-all ${
        selected
          ? 'ring-2 ring-blue-500 bg-blue-50'
          : 'bg-white border border-gray-200 hover:border-gray-300 hover:bg-gray-50'
      }`}
      style={{ borderRadius: '8px' }}
    >
      <div className="flex gap-1 mb-1.5">
        <span
          className="w-3.5 h-3.5"
          style={{
            background: theme.tokens['color-accent'] || theme.colors.primary,
            borderRadius: '3px',
          }}
        />
        <span
          className="w-3.5 h-3.5"
          style={{
            background: theme.tokens['color-accent-2'] || theme.colors.secondary,
            borderRadius: '3px',
          }}
        />
        <span
          className="w-3.5 h-3.5"
          style={{
            background: theme.tokens['color-bg'] || theme.colors.background,
            border: '1px solid rgba(0,0,0,.1)',
            borderRadius: '3px',
          }}
        />
      </div>
      <div className="text-xs font-medium truncate" style={{ color: '#0a0a0a' }}>
        {theme.name_zh}
      </div>
      <div className="text-[10px] text-gray-500 truncate">{theme.name_en}</div>
    </button>
  );
}

// =============================================================================
// Main component
// =============================================================================

type View = 'collapsed' | 'expanded' | 'searching';

export function ThemeSelector({ selectedTheme, onSelect }: ThemeSelectorProps) {
  const [view, setView] = useState<View>('collapsed');
  const [query, setQuery] = useState('');

  const featured = useMemo(() => getFeaturedThemes(), []);

  // Resolve legacy v0.5 IDs (e.g. "professional" -> "corporate-clean")
  const resolvedSelected = resolveThemeId(selectedTheme);
  const isSelectedFeatured = featured.some((t) => t.id === resolvedSelected);

  // ===========================================================================
  // Search view (replaces pill row + drawer when query is non-empty)
  // ===========================================================================
  if (view === 'searching' && query.trim()) {
    const results = searchThemes(query);
    return (
      <div className="bg-white rounded-lg shadow-md p-3 w-80">
        <div className="flex items-center gap-2 mb-2">
          <input
            type="text"
            autoFocus
            placeholder="搜索主题..."
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              if (!e.target.value.trim()) setView('collapsed');
            }}
            className="flex-1 px-2 py-1 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            onClick={() => {
              setQuery('');
              setView('collapsed');
            }}
            className="text-xs text-gray-500 hover:text-gray-700"
          >
            ✕
          </button>
        </div>
        <div className="text-[10px] text-gray-400 mb-2">
          {results.length} 个匹配
        </div>
        {results.length === 0 ? (
          <div className="text-sm text-gray-500 text-center py-6">未找到匹配主题</div>
        ) : (
          <div className="grid grid-cols-3 gap-1.5 max-h-72 overflow-y-auto">
            {results.map((t) => (
              <ThemeChipCard
                key={t.id}
                theme={t}
                selected={t.id === resolvedSelected}
                onClick={() => onSelect(t.id)}
              />
            ))}
          </div>
        )}
      </div>
    );
  }

  // ===========================================================================
  // Default view: pill row + (optional) drawer
  // ===========================================================================
  return (
    <div className="relative">
      <div className="flex items-center gap-2">
        {/* Pill row: 6 featured themes. Horizontal scroll on narrow screens. */}
        <div
          className="flex items-center gap-1.5 overflow-x-auto"
          style={{ maxWidth: '32rem' }}
        >
          {featured.map((t) => (
            <ThemePill
              key={t.id}
              theme={t}
              selected={t.id === resolvedSelected}
              onClick={() => onSelect(t.id)}
            />
          ))}
        </div>

        {/* Search input — typing flips to 'searching' view */}
        <input
          type="text"
          placeholder="🔍"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            if (e.target.value.trim()) setView('searching');
          }}
          className="w-7 h-7 px-1 text-xs text-center border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          title="搜索主题"
        />

        {/* Expand / collapse toggle */}
        {view === 'collapsed' ? (
          <button
            onClick={() => setView('expanded')}
            className="text-xs text-gray-600 hover:text-blue-600 whitespace-nowrap"
          >
            ▾ 全部 {THEMES.length} 个
          </button>
        ) : (
          <button
            onClick={() => setView('collapsed')}
            className="text-xs text-gray-600 hover:text-blue-600 whitespace-nowrap"
          >
            ▴ 收起
          </button>
        )}

        {/* Hint when current selection is not in the 6 featured pills */}
        {!isSelectedFeatured && (
          <span className="text-[10px] text-amber-600 whitespace-nowrap" title="当前主题不在 6 个精选中，点 '全部 N 个' 查看">
            ●
          </span>
        )}
      </div>

      {/* Drawer panel — absolutely positioned below the pill row */}
      {view === 'expanded' && (
        <Drawer
          resolvedSelected={resolvedSelected}
          onSelect={onSelect}
          onCollapse={() => setView('collapsed')}
        />
      )}
    </div>
  );
}

// =============================================================================
// Drawer (expanded view showing all 36 themes grouped by category)
// =============================================================================

function Drawer({
  resolvedSelected,
  onSelect,
  onCollapse,
}: {
  resolvedSelected: string;
  onSelect: (themeId: string) => void;
  onCollapse: () => void;
}) {
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    if (!query.trim()) return null;  // null = show full grouped view
    return searchThemes(query);
  }, [query]);

  return (
    <div
      className="absolute right-0 top-full mt-2 z-30 bg-white rounded-lg shadow-2xl border border-gray-200"
      style={{ width: '28rem' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-2 p-3 border-b border-gray-100">
        <div className="flex items-center gap-2 flex-1">
          <h3 className="text-sm font-semibold text-gray-800 whitespace-nowrap">
            主题 · {THEMES.length}
          </h3>
          <input
            type="text"
            placeholder="搜索..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="flex-1 px-2 py-1 text-xs border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
        <button
          onClick={onCollapse}
          className="text-xs text-gray-500 hover:text-gray-700 whitespace-nowrap"
        >
          ✕
        </button>
      </div>

      {/* Body */}
      <div className="max-h-[28rem] overflow-y-auto p-3">
        {filtered ? (
          // Flat search results
          filtered.length === 0 ? (
            <div className="text-sm text-gray-500 text-center py-8">未找到匹配主题</div>
          ) : (
            <div className="grid grid-cols-3 gap-1.5">
              {filtered.map((t) => (
                <ThemeChipCard
                  key={t.id}
                  theme={t}
                  selected={t.id === resolvedSelected}
                  onClick={() => onSelect(t.id)}
                />
              ))}
            </div>
          )
        ) : (
          // Grouped by category
          <div className="space-y-3">
            {CATEGORY_ORDER.map((cat) => {
              const themes = THEMES.filter((t) => t.category === cat);
              if (themes.length === 0) return null;
              return (
                <div key={cat}>
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <span className="text-xs font-semibold text-gray-700">
                      {CATEGORY_LABELS[cat].zh}
                    </span>
                    <span className="text-[10px] text-gray-400">
                      / {CATEGORY_LABELS[cat].en} · {themes.length}
                    </span>
                  </div>
                  <div className="grid grid-cols-3 gap-1.5">
                    {themes.map((t) => (
                      <ThemeChipCard
                        key={t.id}
                        theme={t}
                        selected={t.id === resolvedSelected}
                        onClick={() => onSelect(t.id)}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Footer attribution */}
      <div className="border-t border-gray-100 px-3 py-2 text-[10px] text-gray-400 text-center">
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
