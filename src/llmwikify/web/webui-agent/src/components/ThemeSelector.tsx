/**
 * PPT Generator - Theme Selector Component
 * Card-style theme selection with preview
 */

import React from 'react';
import { Theme, THEMES } from '../lib/ppt-themes';

interface ThemeSelectorProps {
  selectedTheme: string;
  onSelect: (themeName: string) => void;
}

export function ThemeSelector({ selectedTheme, onSelect }: ThemeSelectorProps) {
  return (
    <div className="bg-white rounded-lg shadow-md p-4">
      <h3 className="text-lg font-semibold mb-3">Themes</h3>
      <div className="grid grid-cols-4 gap-2">
        {THEMES.map((theme) => (
          <button
            key={theme.name}
            onClick={() => onSelect(theme.name)}
            className={`relative p-2 rounded-lg border-2 transition-all ${
              selectedTheme === theme.name
                ? 'border-blue-500 ring-2 ring-blue-200'
                : 'border-gray-200 hover:border-gray-300'
            }`}
          >
            {/* Color Preview */}
            <div className="flex gap-1 mb-1">
              <div
                className="w-4 h-4 rounded-full"
                style={{ backgroundColor: theme.colors.primary }}
              />
              <div
                className="w-4 h-4 rounded-full"
                style={{ backgroundColor: theme.colors.accent }}
              />
              <div
                className="w-4 h-4 rounded-full border"
                style={{ backgroundColor: theme.colors.background }}
              />
            </div>
            <span className="text-xs font-medium">{theme.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export default ThemeSelector;
