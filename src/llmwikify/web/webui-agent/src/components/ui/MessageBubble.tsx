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

  return (
    <div className={`
      max-w-[82%] rounded-lg px-4 py-2.5 text-sm shadow-sm
      ${role === 'user'
        ? 'bg-[var(--accent)] text-white'
        : 'bg-[var(--bg-secondary)] text-[var(--text-primary)]'
      }
      ${className}
    `}>
      <div className="flex items-start gap-2">
        <span className="text-base leading-none mt-0.5">
          {role === 'user' ? '\u{1F464}' : '\u{1F916}'}
        </span>
        <div className="flex-1 min-w-0">
          {thinking && (
            <div className="mb-2">
              <button
                onClick={() => setThinkingExpanded(!thinkingExpanded)}
                className="flex items-center gap-1 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors w-full text-left"
              >
                <span className="text-[10px]">{thinkingExpanded ? '\u25BC' : '\u25B6'}</span>
                <span className="italic">
                  {streaming ? 'Thinking...' : 'Thinking'}
                </span>
                {streaming && (
                  <span className="thinking-dots ml-1" />
                )}
              </button>
              {thinkingExpanded && (
                <div className="mt-1.5 p-2 rounded bg-[var(--bg-tertiary)]/50 border border-[var(--border)]">
                  <pre className="whitespace-pre-wrap font-sans text-xs text-[var(--text-secondary)] leading-relaxed">
                    {thinking}
                  </pre>
                </div>
              )}
            </div>
          )}
          {role === 'assistant' ? (
            <>
              {hasContent ? (
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
              ) : streaming && thinking ? (
                <div className="text-xs text-[var(--text-secondary)] italic">Waiting for response...</div>
              ) : null}
            </>
          ) : (
            <pre className="whitespace-pre-wrap font-sans">{content}</pre>
          )}
          {streaming && role === 'assistant' && hasContent && (
            <span className="streaming-cursor text-[var(--accent)]" />
          )}
          {timestamp && (
            <div className={`
              text-xs mt-1
              ${role === 'user' ? 'text-blue-200' : 'text-[var(--text-secondary)]'}
            `}>
              {timestamp}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
