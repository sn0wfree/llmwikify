import { cn } from '@/lib/utils';

interface LegacySelectProps {
  value?: string;
  onChange?: (e: React.ChangeEvent<HTMLSelectElement>) => void;
  children: React.ReactNode;
  className?: string;
  disabled?: boolean;
}

export function Select({ value, onChange, children, className, disabled }: LegacySelectProps) {
  return (
    <select
      value={value}
      onChange={onChange}
      disabled={disabled}
      className={cn(
        'h-8 rounded-lg border border-input bg-transparent px-2.5 py-1 text-sm transition-colors outline-none',
        'focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50',
        'disabled:cursor-not-allowed disabled:opacity-50',
        'dark:bg-input/30',
        className,
      )}
    >
      {children}
    </select>
  );
}
