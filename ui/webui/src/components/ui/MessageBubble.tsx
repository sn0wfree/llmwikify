import { useState, useRef, useEffect } from 'react';
import { Bot, User, Copy, Check, RefreshCw, Quote } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

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
  role,
  content,
  thinking,
  timestamp,
  streaming = false,
  className = '',
  onRegenerate,
  onQuote,
}: MessageBubbleProps) {
  const [thinkingExpanded, setThinkingExpanded] = useState(false);
  const [copyState, setCopyState] = useState<'idle' | 'copied'>('idle');
  const copyResetRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasContent = content && content.trim().length > 0;
  const isUser = role === 'user';
  const Avatar = isUser ? User : Bot;
  const avatarLabel = isUser ? 'You' : 'Assistant';

  useEffect(() => {
    return () => {
      if (copyResetRef.current) clearTimeout(copyResetRef.current);
    };
  }, []);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopyState('copied');
      if (copyResetRef.current) clearTimeout(copyResetRef.current);
      copyResetRef.current = setTimeout(() => setCopyState('idle'), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  const handleQuote = () => {
    if (onQuote) onQuote(content);
  };

  if (isUser) {
    return (
      <div className={`flex justify-end gap-2 animate-chat-fade-in ${className}`}>
        <div className="max-w-[75%] flex flex-col items-end">
          <div className="flex items-center gap-1.5 mb-1 text-xs text-[var(--text-secondary)]">
            <span className="font-medium">{avatarLabel}</span>
          </div>
          <div className="rounded-2xl rounded-br-md px-4 py-2.5 text-sm bg-[var(--accent)] text-white shadow-sm">
            <pre className="whitespace-pre-wrap font-sans">{content}</pre>
            {timestamp && <div className="text-xs mt-1 text-blue-200">{timestamp}</div>}
          </div>
        </div>
        <div
          className="shrink-0 w-7 h-7 rounded-full bg-[var(--accent)]/15 border border-[var(--accent)]/30 flex items-center justify-center"
          aria-label={avatarLabel}
        >
          <Avatar className="w-4 h-4 text-[var(--accent)]" />
        </div>
      </div>
    );
  }

  return (
    <div className={`flex justify-start gap-2 animate-chat-fade-in ${className}`}>
      <div
        className="shrink-0 w-7 h-7 rounded-full bg-[var(--bg-tertiary)]/60 border border-[var(--border)] flex items-center justify-center"
        aria-label={avatarLabel}
      >
        <Avatar className="w-4 h-4 text-[var(--text-secondary)]" />
      </div>
      <div className="max-w-[88%] w-full space-y-1 group/bubble">
        <div className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
          <span className="font-medium">{avatarLabel}</span>
        </div>

        {thinking && (
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)]/30 overflow-hidden">
            <button
              onClick={() => setThinkingExpanded(!thinkingExpanded)}
              className="flex items-center gap-2 px-3 py-1.5 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors w-full text-left"
            >
              <span className="text-[10px]">{thinkingExpanded ? '\u25BC' : '\u25B6'}</span>
              <span className="font-medium">
                {streaming ? 'Thinking...' : 'Thinking'}
              </span>
              {streaming && <span className="thinking-dots ml-1" />}
            </button>
            {thinkingExpanded && (
              <div className="px-3 pb-3 pt-0">
                <pre className="whitespace-pre-wrap font-sans text-xs text-[var(--text-secondary)] leading-relaxed">
                  {thinking}
                </pre>
              </div>
            )}
          </div>
        )}

        {hasContent ? (
          <div className="rounded-lg bg-[var(--bg-secondary)] border border-[var(--border)] px-4 py-3 relative">
            <div
              className="prose prose-sm prose-neutral dark:prose-invert max-w-none
              prose-headings:mt-2 prose-headings:mb-1
              prose-p:my-1 prose-ul:my-1 prose-ol:my-1
              prose-li:my-0 prose-pre:my-2
              prose-code:text-xs prose-code:bg-[var(--bg-tertiary)] prose-code:px-1 prose-code:py-0.5 prose-code:rounded
              prose-pre:bg-[var(--bg-tertiary)] prose-pre:rounded prose-pre:p-2
              prose-a:text-[var(--accent)] prose-a:underline
              prose-table:text-xs prose-th:px-2 prose-th:py-1 prose-td:px-2 prose-td:py-1
              prose-blockquote:border-l-2 prose-blockquote:border-[var(--border)] prose-blockquote:pl-2 prose-blockquote:italic
            "
            >
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            </div>
            {streaming && <span className="streaming-cursor text-[var(--accent)]" />}
          </div>
        ) : streaming && thinking ? (
          <div className="flex items-center gap-2 text-xs text-[var(--text-secondary)] italic px-1">
            <span className="thinking-dots" />
            <span>Waiting for response...</span>
          </div>
        ) : null}

        <div className="flex items-center justify-between gap-2 px-1 min-h-[20px]">
          {timestamp && (
            <div className="text-xs text-[var(--text-secondary)] opacity-0 group-hover/bubble:opacity-100 transition-opacity">
              {timestamp}
            </div>
          )}
          {hasContent && !streaming && (
            <div className="flex items-center gap-1 opacity-0 group-hover/bubble:opacity-100 transition-opacity ml-auto">
              <button
                onClick={handleCopy}
                className="p-1 rounded text-[var(--text-secondary)] hover:text-[var(--accent)] hover:bg-[var(--bg-tertiary)]/60 transition-colors"
                title={copyState === 'copied' ? 'Copied!' : 'Copy message'}
                aria-label="Copy message"
              >
                {copyState === 'copied' ? (
                  <Check className="w-3.5 h-3.5 text-[var(--success)]" />
                ) : (
                  <Copy className="w-3.5 h-3.5" />
                )}
              </button>
              {onRegenerate && (
                <button
                  onClick={onRegenerate}
                  className="p-1 rounded text-[var(--text-secondary)] hover:text-[var(--accent)] hover:bg-[var(--bg-tertiary)]/60 transition-colors"
                  title="Regenerate response"
                  aria-label="Regenerate response"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                </button>
              )}
              {onQuote && (
                <button
                  onClick={handleQuote}
                  className="p-1 rounded text-[var(--text-secondary)] hover:text-[var(--accent)] hover:bg-[var(--bg-tertiary)]/60 transition-colors"
                  title="Quote in next message"
                  aria-label="Quote in next message"
                >
                  <Quote className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
