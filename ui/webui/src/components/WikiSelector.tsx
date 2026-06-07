/**
 * WikiSelector - Dropdown component for switching between wikis.
 * Shows current wiki name, allows switching, and has a "+" button for adding new wikis.
 */

import { useState } from 'react';
import { useWikiStore } from '../stores/wikiStore';

interface WikiSelectorProps {
  onOpenManager?: () => void;
}

export function WikiSelector({ onOpenManager }: WikiSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const { wikis, currentWikiId, switchWiki, currentWiki } = useWikiStore();

  const current = currentWiki();

  // No wikis - show prompt to add one
  if (wikis.length === 0) {
    return (
      <div className="px-3 py-2">
        <div className="text-sm font-medium text-slate-200">No Wiki</div>
        <button
          onClick={onOpenManager}
          className="mt-1 text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Add Wiki
        </button>
      </div>
    );
  }

  if (wikis.length <= 1) {
    const current = currentWiki();
    return (
      <div className="px-3 py-2">
        <div className="text-sm font-medium text-slate-200">
          {current?.name || 'Wiki'}
        </div>
        {current?.page_count !== undefined && (
          <div className="text-xs text-slate-500">
            {current.page_count} pages
          </div>
        )}
        <button
          onClick={onOpenManager}
          className="mt-1 text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Add Wiki
        </button>
      </div>
    );
  }

  return (
    <div className="relative px-2 py-2">
      {/* Current wiki display */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-3 py-2 bg-slate-700 rounded-lg hover:bg-slate-600 transition-colors"
      >
        <div className="text-left">
          <div className="text-sm font-medium text-slate-200">
            {current?.name || 'Select Wiki'}
          </div>
          {current && (
            <div className="text-xs text-slate-500">
              {current.page_count} pages · {current.type}
            </div>
          )}
        </div>
        <svg
          className={`w-4 h-4 text-slate-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Dropdown menu */}
      {isOpen && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setIsOpen(false)}
          />

          {/* Menu */}
          <div className="absolute left-2 right-2 mt-1 bg-slate-800 border border-slate-700 rounded-lg shadow-lg z-50 overflow-hidden">
            <div className="py-1">
              {wikis.map((wiki) => (
                <button
                  key={wiki.wiki_id}
                  onClick={() => {
                    switchWiki(wiki.wiki_id);
                    setIsOpen(false);
                  }}
                  className={`w-full px-3 py-2 text-left hover:bg-slate-700 transition-colors ${
                    wiki.wiki_id === currentWikiId ? 'bg-slate-700' : ''
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-sm font-medium text-slate-200">
                        {wiki.name}
                      </div>
                      <div className="text-xs text-slate-500">
                        {wiki.page_count} pages · {wiki.type}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {wiki.is_default && (
                        <span className="text-xs bg-blue-600 text-white px-2 py-0.5 rounded">
                          Default
                        </span>
                      )}
                      {wiki.wiki_id === currentWikiId && (
                        <svg className="w-4 h-4 text-blue-400" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                        </svg>
                      )}
                    </div>
                  </div>
                </button>
              ))}
            </div>

            {/* Add wiki button */}
            <div className="border-t border-slate-700 py-1">
              <button
                onClick={() => {
                  setIsOpen(false);
                  onOpenManager?.();
                }}
                className="w-full px-3 py-2 text-left text-sm text-blue-400 hover:bg-slate-700 transition-colors flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                Add Wiki
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
