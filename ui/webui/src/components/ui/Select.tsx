import { cn } from '@/lib/utils';

interface SelectOption {
  value: string;
  label: string;
}

interface LegacySelectProps {
  value?: string;
  onChange?: (e: React.ChangeEvent<HTMLSelectElement>) => void;
  children?: React.ReactNode;
  options?: SelectOption[];
  className?: string;
  disabled?: boolean;
}

export function Select({ value, onChange, children, options, className, disabled }: LegacySelectProps) {
  return (
    <select
      value={value}
      onChange={onChange}
      disabled={disabled}
      className={cn(
        'h-9 rounded-md border border-input bg-card px-3 py-1 text-sm transition-colors outline-none',
        'focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50',
        'disabled:cursor-not-allowed disabled:opacity-50',
        'dark:bg-input/30',
        'min-w-0',
        className,
      )}
    >
      {options
        ? options.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))
        : children}
    </select>
  );
}
