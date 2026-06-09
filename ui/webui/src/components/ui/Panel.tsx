import { cn } from '@/lib/utils';

interface PanelProps {
  children: React.ReactNode;
  border?: 'top' | 'bottom' | 'all' | 'none';
  className?: string;
}

export function Panel({ children, border = 'none', className }: PanelProps) {
  const borderClass = {
    top: 'border-t',
    bottom: 'border-b',
    all: 'border',
    none: '',
  }[border];

  return (
    <div className={cn('px-4 py-2', borderClass, 'border-border', className)}>
      {children}
    </div>
  );
}
