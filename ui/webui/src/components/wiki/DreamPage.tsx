import { useState } from 'react';
import { WikiDreamProposals } from './WikiDreamProposals';
import { WikiDreamLog } from './WikiDreamLog';
import { cn } from '@/lib/utils';

export function DreamPage() {
  const [tab, setTab] = useState<'proposals' | 'log'>('proposals');

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="shrink-0 border-b border-border/50 px-6 py-3">
        <div className="flex items-center gap-2">
          <h1 className="text-lg font-semibold text-foreground">Dream</h1>
          <div className="inline-flex p-0.5 rounded-md bg-white/[0.04] border border-border/40 ml-4">
            {(['proposals', 'log'] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={cn(
                  'px-3 py-1 text-xs font-medium rounded transition-colors',
                  tab === t
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {t === 'proposals' ? 'Proposals' : 'Log'}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {tab === 'proposals' ? <WikiDreamProposals /> : <WikiDreamLog />}
      </div>
    </div>
  );
}
