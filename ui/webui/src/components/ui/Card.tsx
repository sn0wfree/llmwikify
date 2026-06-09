import { ReactNode } from 'react';

interface CardProps {
  children: ReactNode;
  className?: string;
  variant?: 'default' | 'bordered';
  padding?: 'none' | 'sm' | 'md' | 'lg';
}

export function Card({
  children,
  className = '',
  variant = 'default',
  padding = 'md',
}: CardProps) {
  const paddingMap = { none: '', sm: 'p-2', md: 'p-3', lg: 'p-4' };
  return (
    <div className={`
      bg-[var(--bg-secondary)] rounded-lg
      ${variant === 'bordered' ? 'border border-[var(--border)]' : ''}
      ${paddingMap[padding]}
      ${className}
    `}>
      {children}
    </div>
  );
}