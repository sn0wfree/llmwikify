import { ChangeEvent, KeyboardEvent, useRef, useEffect } from 'react';

interface InputProps {
  value: string;
  onChange: (e: ChangeEvent<HTMLTextAreaElement>) => void;
  onKeyDown?: (e: KeyboardEvent<HTMLTextAreaElement>) => void;
  placeholder?: string;
  disabled?: boolean;
  rows?: number;
  className?: string;
}

export function Input({
  value,
  onChange,
  onKeyDown,
  placeholder = '',
  disabled = false,
  rows = 1,
  className = '',
}: InputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + 'px';
    }
  }, [value]);

  return (
    <textarea
      ref={textareaRef}
      value={value}
      onChange={onChange}
      onKeyDown={onKeyDown}
      placeholder={placeholder}
      disabled={disabled}
      rows={rows}
      className={`
        w-full bg-[var(--bg-secondary)] border border-[var(--border)]
        rounded-md px-3 py-2.5 pr-10 text-sm text-[var(--text-primary)]
        placeholder-[var(--text-secondary)]
        resize-none
        focus:outline-none focus:border-[var(--accent)]
        focus:ring-2 focus:ring-[var(--accent)]/40
        transition-all duration-200
        disabled:opacity-50
        ${className}
      `}
      style={{ minHeight: '44px', maxHeight: '120px' }}
    />
  );
}