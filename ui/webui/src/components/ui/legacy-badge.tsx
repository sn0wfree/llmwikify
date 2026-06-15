import type React from 'react';
import { Badge as ShadcnBadge } from './badge';

type LegacyVariant = 'default' | 'secondary' | 'destructive' | 'success' | 'warning' | 'error' | 'info' | 'outline';

type ShadcnBadgeProps = React.ComponentProps<typeof ShadcnBadge>;

const variantMap: Record<LegacyVariant, ShadcnBadgeProps['variant']> = {
  default: 'default',
  secondary: 'secondary',
  destructive: 'destructive',
  success: 'secondary',
  warning: 'outline',
  error: 'destructive',
  info: 'outline',
  outline: 'outline',
};

type LegacyBadgeProps = Omit<ShadcnBadgeProps, 'variant'> & {
  variant?: LegacyVariant;
};

export function Badge({ variant = 'default', className, ...props }: LegacyBadgeProps) {
  return (
    <ShadcnBadge
      variant={variantMap[variant]}
      className={className}
      {...props}
    />
  );
}
