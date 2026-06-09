import { Badge as ShadcnBadge, type BadgeProps as ShadcnBadgeProps } from './badge';

type LegacyVariant = 'default' | 'success' | 'warning' | 'error' | 'info';

const variantMap: Record<LegacyVariant, ShadcnBadgeProps['variant']> = {
  default: 'default',
  success: 'secondary',
  warning: 'outline',
  error: 'destructive',
  info: 'outline',
};

interface LegacyBadgeProps {
  children: React.ReactNode;
  variant?: LegacyVariant;
  className?: string;
}

export function Badge({ variant = 'default', className, ...props }: LegacyBadgeProps) {
  return (
    <ShadcnBadge
      variant={variantMap[variant]}
      className={className}
      {...props}
    />
  );
}
