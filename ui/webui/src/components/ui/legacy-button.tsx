import type React from 'react';
import { Button as ShadcnButton } from './button';

type LegacyVariant = 'primary' | 'success' | 'danger' | 'secondary' | 'ghost' | 'outline';
type LegacySize = 'sm' | 'md';

type ShadcnButtonProps = React.ComponentProps<typeof ShadcnButton>;

const variantMap: Record<LegacyVariant, ShadcnButtonProps['variant']> = {
  primary: 'default',
  success: 'default',
  danger: 'destructive',
  secondary: 'secondary',
  ghost: 'ghost',
  outline: 'outline',
};

const sizeMap: Record<LegacySize, ShadcnButtonProps['size']> = {
  sm: 'sm',
  md: 'default',
};

type LegacyButtonProps = Omit<ShadcnButtonProps, 'variant' | 'size'> & {
  variant?: LegacyVariant;
  size?: LegacySize;
};

export function Button({ variant = 'primary', size = 'md', className, ...props }: LegacyButtonProps) {
  return (
    <ShadcnButton
      variant={variantMap[variant]}
      size={sizeMap[size]}
      className={className}
      {...props}
    />
  );
}
