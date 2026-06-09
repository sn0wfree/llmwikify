/**
 * WikiSelector - Dropdown for switching between wikis.
 * Glass morphism + smooth expand animation.
 */

import { useState, useRef, useEffect } from 'react';
import { ChevronDown, Plus, Check, BookOpen } from 'lucide-react';
import { useWikiStore } from '../../stores/wikiStore';
import { cn } from '@/lib/utils';

interface WikiSelectorProps {
  onOpenManager?: () => void;
}

export function WikiSelector({ onOpenManager }: WikiSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const { wikis, currentWikiId, switchWiki, currentWiki } = useWikiStore();
  const wrapperRef = useRef<HTMLDivElement>(null);

  const current = currentWiki();

  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [isOpen]);

  if (wikis.length === 0) {
    return (
      <div className="px-3 py-2 m-2 mb-0">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-muted/60 border border-border/40 flex items-center justify-center">
            <BookOpen className="w-3.5 h-3.5 text-muted-foreground" />
          </div>
          <div className="text-sm font-medium text-muted-foreground">No wiki</div>
        </div>
        <button
          onClick={onOpenManager}
          className="mt-2 w-full flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-md text-xs font-medium text-primary bg-primary/10 hover:bg-primary/20 transition-colors"
        >
          <Plus className="w-3 h-3" />
          Add Wiki
        </button>
      </div>
    );
  }

  return (
    <div ref={wrapperRef} className="relative px-2 py-2">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          'w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg transition-all',
          'glass hover:bg-white/[0.06]',
          isOpen && 'bg-white/[0.06] ring-1 ring-primary/30',
        )}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
      >
        <div className="w-7 h-7 rounded-md bg-gradient-to-br from-primary/30 to-accent/30 border border-primary/20 flex items-center justify-center shrink-0">
          <BookOpen className="w-3.5 h-3.5 text-primary" />
        </div>
        <div className="flex-1 min-w-0 text-left">
          <div className="text-sm font-medium text-foreground truncate">
            {current?.name || 'Select Wiki'}
          </div>
          {current && (
            <div className="text-[10px] text-muted-foreground truncate">
              {current.page_count} pages · {current.type}
            </div>
          )}
        </div>
        <ChevronDown
          className={cn(
            'w-3.5 h-3.5 text-muted-foreground transition-transform duration-200',
            isOpen && 'rotate-180',
          )}
        />
      </button>

      {isOpen && (
        <div
          className="absolute left-2 right-2 mt-1 glass-strong rounded-lg shadow-elevated z-50 overflow-hidden animate-slide-up"
          role="listbox"
        >
          <div className="py-1 max-h-64 overflow-y-auto">
            {wikis.map((wiki) => {
              const isActive = wiki.wiki_id === currentWikiId;
              return (
                <button
                  key={wiki.wiki_id}
                  onClick={() => {
                    switchWiki(wiki.wiki_id);
                    setIsOpen(false);
                  }}
                  className={cn(
                    'w-full px-3 py-2 text-left transition-colors flex items-center gap-2',
                    isActive ? 'bg-primary/12' : 'hover:bg-white/[0.04]',
                  )}
                  role="option"
                  aria-selected={isActive}
                >
                  <div className="w-6 h-6 rounded-md bg-muted/60 border border-border/40 flex items-center justify-center shrink-0">
                    <BookOpen className="w-3 h-3 text-muted-foreground" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-foreground truncate">
                      {wiki.name}
                    </div>
                    <div className="text-[10px] text-muted-foreground truncate">
                      {wiki.page_count} pages · {wiki.type}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {wiki.is_default && (
                      <span className="text-[9px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded bg-primary/15 text-primary">
                        Default
                      </span>
                    )}
                    {isActive && <Check className="w-3.5 h-3.5 text-primary" />}
                  </div>
                </button>
              );
            })}
          </div>

          <div className="border-t border-border/40">
            <button
              onClick={() => {
                setIsOpen(false);
                onOpenManager?.();
              }}
              className="w-full px-3 py-2 text-left text-xs text-primary hover:bg-white/[0.04] transition-colors flex items-center gap-2"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Add Wiki</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
