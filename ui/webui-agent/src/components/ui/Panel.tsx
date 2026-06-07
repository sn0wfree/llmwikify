import { ReactNode } from 'react';

interface PanelProps {
  children: ReactNode;
  className?: string;
  border?: 'top' | 'bottom' | 'all' | 'none';
}

const borderMap = {
  top: 'border-t border-[var(--border)]',
  bottom: 'border-b border-[var(--border)]',
  all: 'border border-[var(--border)]',
  none: '',
};

export function Panel({ children, className = '', border = 'top' }: PanelProps) {
  return (
    <div className={`
      bg-[var(--bg-secondary)] ${borderMap[border]}
      p-3
      ${className}
    `}>
      {children}
    </div>
  );
}