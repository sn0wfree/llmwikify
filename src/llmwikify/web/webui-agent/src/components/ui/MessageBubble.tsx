interface MessageBubbleProps {
  role: 'user' | 'assistant';
  content: string;
  timestamp?: string;
  streaming?: boolean;
  className?: string;
}

export function MessageBubble({
  role,
  content,
  timestamp,
  streaming = false,
  className = '',
}: MessageBubbleProps) {
  return (
    <div className={`
      max-w-[82%] rounded-lg px-4 py-2.5 text-sm shadow-sm
      ${role === 'user'
        ? 'bg-[var(--accent)] text-white'
        : 'bg-[var(--bg-secondary)] text-[var(--text-primary)]'
      }
      ${className}
    `}>
      <pre className="whitespace-pre-wrap font-sans">{content}</pre>
      {streaming && role === 'assistant' && (
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
  );
}