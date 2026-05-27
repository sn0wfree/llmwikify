import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface MessageBubbleProps {
  role: 'user' | 'assistant';
  content: string;
  thinking?: string;
  timestamp?: string;
  streaming?: boolean;
  className?: string;
}

export function MessageBubble({
  role,
  content,
  thinking,
  timestamp,
  streaming = false,
  className = '',
}: MessageBubbleProps) {
  const [thinkingExpanded, setThinkingExpanded] = useState(false);
  const hasContent = content && content.trim().length > 0;

  if (role === 'user') {
    return (
      <div className={`flex justify-end ${className}`}>
        <div className="max-w-[75%] rounded-2xl rounded-br-md px-4 py-2.5 text-sm bg-[var(--accent)] text-white shadow-sm">
          <pre className="whitespace-pre-wrap font-sans">{content}</pre>
          {timestamp && (
            <div className="text-xs mt-1 text-blue-200">{timestamp}</div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={`flex justify-start ${className}`}>
      <div className="max-w-[88%] w-full space-y-1">
        {/* Thinking block */}
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

        {/* Content block */}
        {hasContent ? (
          <div className="rounded-lg bg-[var(--bg-secondary)] border border-[var(--border)] px-4 py-3">
            <div className="prose prose-sm prose-neutral dark:prose-invert max-w-none
              prose-headings:mt-2 prose-headings:mb-1
              prose-p:my-1 prose-ul:my-1 prose-ol:my-1
              prose-li:my-0 prose-pre:my-2
              prose-code:text-xs prose-code:bg-[var(--bg-tertiary)] prose-code:px-1 prose-code:py-0.5 prose-code:rounded
              prose-pre:bg-[var(--bg-tertiary)] prose-pre:rounded prose-pre:p-2
              prose-a:text-[var(--accent)] prose-a:underline
              prose-table:text-xs prose-th:px-2 prose-th:py-1 prose-td:px-2 prose-td:py-1
              prose-blockquote:border-l-2 prose-blockquote:border-[var(--border)] prose-blockquote:pl-2 prose-blockquote:italic
            ">
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

        {/* Timestamp */}
        {timestamp && (
          <div className="text-xs text-[var(--text-secondary)] px-1">{timestamp}</div>
        )}
      </div>
    </div>
  );
}
