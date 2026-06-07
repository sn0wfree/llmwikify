import { useState } from 'react';
import { useAgentWikiStore } from '../stores/agentWikiStore';
import { Card } from './ui/Card';
import { Button } from './ui/Button';

export function WikiSelector() {
  const [isOpen, setIsOpen] = useState(false);
  const { wikis, currentWikiId, switchWiki, currentWiki } = useAgentWikiStore();
  const current = currentWiki();

  if (wikis.length === 0) {
    return (
      <div className="px-3 py-2 text-sm text-[var(--text-secondary)]">
        No wiki loaded
      </div>
    );
  }

  if (wikis.length <= 1) {
    return (
      <div className="px-3 py-2">
        <div className="text-sm font-medium text-[var(--text-primary)]">
          {current?.name || 'Wiki'}
        </div>
        {current?.page_count !== undefined && (
          <div className="text-xs text-[var(--text-secondary)]">
            {current.page_count} pages
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="relative px-2 py-2">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-3 py-2 bg-[var(--bg-tertiary)] rounded-lg hover:opacity-80 transition-opacity"
      >
        <div className="text-left">
          <div className="text-sm font-medium text-[var(--text-primary)]">
            {current?.name || 'Select Wiki'}
          </div>
          {current && (
            <div className="text-xs text-[var(--text-secondary)]">
              {current.page_count} pages
            </div>
          )}
        </div>
        <svg
          className={`w-4 h-4 text-[var(--text-secondary)] transition-transform ${isOpen ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />
          <div className="absolute left-2 right-2 mt-1 bg-[var(--bg-secondary)] border border-[var(--border)] rounded-lg shadow-lg z-50 overflow-hidden">
            <div className="py-1">
              {wikis.map((wiki) => (
                <button
                  key={wiki.wiki_id}
                  onClick={() => {
                    switchWiki(wiki.wiki_id);
                    setIsOpen(false);
                  }}
                  className={`w-full px-3 py-2 text-left hover:bg-[var(--bg-tertiary)] transition-colors ${
                    wiki.wiki_id === currentWikiId ? 'bg-[var(--bg-tertiary)]' : ''
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-sm font-medium text-[var(--text-primary)]">
                        {wiki.name}
                      </div>
                      <div className="text-xs text-[var(--text-secondary)]">
                        {wiki.page_count} pages
                      </div>
                    </div>
                    {wiki.wiki_id === currentWikiId && (
                      <svg className="w-4 h-4 text-[var(--accent)]" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                    )}
                  </div>
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}