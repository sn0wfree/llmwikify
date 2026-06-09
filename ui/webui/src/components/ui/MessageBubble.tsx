import { useState, useRef, useEffect } from 'react';
import { Bot, User, Copy, Check, RefreshCw, Quote, Brain } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '@/lib/utils';

interface MessageBubbleProps {
  role: 'user' | 'assistant';
  content: string;
  thinking?: string;
  timestamp?: string;
  streaming?: boolean;
  className?: string;
  onRegenerate?: () => void;
  onQuote?: (text: string) => void;
}

export function MessageBubble({
  role, content, thinking, timestamp, streaming = false,
  className = '', onRegenerate, onQuote,
}: MessageBubbleProps) {
  const [thinkingExpanded, setThinkingExpanded] = useState(true);
  const [copyState, setCopyState] = useState<'idle' | 'copied'>('idle');
  const copyResetRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasContent = content && content.trim().length > 0;
  const isUser = role === 'user';
  const Avatar = isUser ? User : Bot;

  useEffect(() => {
    return () => { if (copyResetRef.current) clearTimeout(copyResetRef.current); };
  }, []);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopyState('copied');
      if (copyResetRef.current) clearTimeout(copyResetRef.current);
      copyResetRef.current = setTimeout(() => setCopyState('idle'), 1500);
    } catch { /* clipboard unavailable */ }
  };

  if (isUser) {
    return (
      <div className={cn('flex justify-end gap-2.5 animate-message-in', className)}>
        <div className="max-w-[80%] flex flex-col items-end gap-1">
          <div
            className="rounded-3xl rounded-tr-md px-4 py-2.5 text-sm text-foreground shadow-soft"
            style={{ background: 'var(--gradient-user-bubble)' }}
          >
            <div className="whitespace-pre-wrap break-words leading-relaxed">
              {content}
            </div>
          </div>
          {timestamp && (
            <div className="text-[10px] text-muted-foreground/70 px-1">{timestamp}</div>
          )}
        </div>
        <div className="shrink-0 w-7 h-7 rounded-full bg-gradient-to-br from-primary to-accent flex items-center justify-center shadow-soft">
          <Avatar className="w-3.5 h-3.5 text-primary-foreground" />
        </div>
      </div>
    );
  }

  return (
    <div className={cn('flex justify-start gap-2.5 animate-message-in', className)}>
      <div className="shrink-0 w-7 h-7 rounded-full bg-gradient-to-br from-primary/30 to-accent/30 border border-primary/20 flex items-center justify-center">
        <Avatar className="w-3.5 h-3.5 text-primary" />
      </div>
      <div className="max-w-[88%] w-full space-y-1.5 group/bubble min-w-0">
        <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground px-1">
          <span className="font-semibold uppercase tracking-wider">Assistant</span>
          {streaming && (
            <span className="flex items-center gap-1 text-primary/80">
              <span className="thinking-dots scale-75 origin-left"><span /><span /><span /></span>
              <span>streaming</span>
            </span>
          )}
        </div>

        {thinking && (
          <div className="rounded-lg border border-thinking/30 bg-thinking/5 overflow-hidden">
            <button
              onClick={() => setThinkingExpanded(!thinkingExpanded)}
              className="flex items-center gap-2 px-3 py-1.5 text-xs text-thinking hover:text-foreground transition-colors w-full text-left"
            >
              <Brain className="w-3.5 h-3.5 shrink-0" />
              <span className="font-semibold italic">
                {streaming ? 'Reasoning…' : 'Reasoning'}
              </span>
              {streaming && !thinkingExpanded && (
                <span className="thinking-dots scale-75 origin-left"><span /><span /><span /></span>
              )}
              <span className="ml-auto text-[10px] text-muted-foreground/70">
                {thinkingExpanded ? '▾' : '▸'}
              </span>
            </button>
            {thinkingExpanded && (
              <div className="px-3 pb-3 pt-1 animate-slide-up">
                <pre className="whitespace-pre-wrap font-sans text-xs italic text-thinking/90 leading-relaxed">
                  {thinking}
                </pre>
              </div>
            )}
          </div>
        )}

        {hasContent ? (
          <div className="rounded-lg px-1 py-1 relative">
            <div className="prose prose-sm prose-neutral dark:prose-invert max-w-none
              prose-headings:mt-2 prose-headings:mb-1 prose-headings:font-semibold
              prose-p:my-1.5 prose-p:leading-relaxed
              prose-ul:my-1.5 prose-ol:my-1.5
              prose-li:my-0.5
              prose-pre:my-2 prose-pre:rounded-lg prose-pre:border prose-pre:border-border
              prose-code:text-xs prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:font-mono prose-code:before:content-none prose-code:after:content-none
              prose-pre:bg-muted/60 prose-pre:p-3
              prose-a:text-primary prose-a:no-underline hover:prose-a:underline
              prose-table:text-xs prose-th:px-2 prose-th:py-1 prose-td:px-2 prose-td:py-1
              prose-blockquote:border-l-2 prose-blockquote:border-primary prose-blockquote:pl-3 prose-blockquote:italic prose-blockquote:text-muted-foreground
              prose-hr:border-border
            ">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            </div>
            {streaming && <span className="streaming-cursor" />}
          </div>
        ) : streaming && thinking ? (
          <div className="flex items-center gap-2 text-xs text-muted-foreground italic px-1">
            <span className="thinking-dots"><span /><span /><span /></span>
            <span>Waiting for response…</span>
          </div>
        ) : null}

        <div className="flex items-center justify-between gap-2 px-1 min-h-[20px]">
          {timestamp && (
            <div className="text-[10px] text-muted-foreground/70 opacity-0 group-hover/bubble:opacity-100 transition-opacity">
              {timestamp}
            </div>
          )}
          {hasContent && !streaming && (
            <div className="flex items-center gap-0.5 opacity-0 group-hover/bubble:opacity-100 transition-opacity ml-auto">
              <ActionButton
                onClick={handleCopy}
                title="Copy"
                aria-label="Copy message"
              >
                {copyState === 'copied' ? (
                  <Check className="w-3.5 h-3.5 text-success" />
                ) : (
                  <Copy className="w-3.5 h-3.5" />
                )}
              </ActionButton>
              {onRegenerate && (
                <ActionButton onClick={onRegenerate} title="Regenerate" aria-label="Regenerate response">
                  <RefreshCw className="w-3.5 h-3.5" />
                </ActionButton>
              )}
              {onQuote && (
                <ActionButton onClick={() => onQuote(content)} title="Quote" aria-label="Quote in next message">
                  <Quote className="w-3.5 h-3.5" />
                </ActionButton>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ActionButton({
  children, onClick, title, ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      onClick={onClick}
      title={title}
      className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-white/[0.06] transition-colors"
      {...rest}
    >
      {children}
    </button>
  );
}
