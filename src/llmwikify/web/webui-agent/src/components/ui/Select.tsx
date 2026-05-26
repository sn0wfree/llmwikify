import { ChangeEvent } from 'react';

interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps {
  value: string;
  onChange: (e: ChangeEvent<HTMLSelectElement>) => void;
  options: SelectOption[];
  disabled?: boolean;
  className?: string;
}

export function Select({ value, onChange, options, disabled = false, className = '' }: SelectProps) {
  return (
    <select
      value={value}
      onChange={onChange}
      disabled={disabled}
      className={`
        w-full bg-[var(--bg-secondary)] border border-[var(--border)]
        rounded-md px-3 py-2.5 text-sm text-[var(--text-primary)]
        focus:outline-none focus:border-[var(--accent)]
        focus:ring-2 focus:ring-[var(--accent)]/40
        transition-all duration-200
        disabled:opacity-50
        ${className}
      `}
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  );
}