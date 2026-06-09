import { Card as ShadcnCard } from './card';
import { cn } from '@/lib/utils';

interface LegacyCardProps {
  children: React.ReactNode;
  className?: string;
  variant?: 'default' | 'bordered';
  padding?: 'none' | 'sm' | 'md' | 'lg';
}

const paddingMap = { none: '', sm: 'p-2', md: '', lg: 'p-6' };

export function Card({ children, className = '', variant = 'default', padding = 'md' }: LegacyCardProps) {
  return (
    <ShadcnCard
      className={cn(
        variant === 'bordered' && 'ring-border',
        paddingMap[padding],
        className,
      )}
    >
      {children}
    </ShadcnCard>
  );
}
