import { Button as ShadcnButton, type ButtonProps as ShadcnButtonProps } from './button';

type LegacyVariant = 'primary' | 'success' | 'danger' | 'secondary' | 'ghost';
type LegacySize = 'sm' | 'md';

const variantMap: Record<LegacyVariant, ShadcnButtonProps['variant']> = {
  primary: 'default',
  success: 'default',
  danger: 'destructive',
  secondary: 'secondary',
  ghost: 'ghost',
};

const sizeMap: Record<LegacySize, ShadcnButtonProps['size']> = {
  sm: 'sm',
  md: 'default',
};

interface LegacyButtonProps {
  children: React.ReactNode;
  onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void;
  type?: 'button' | 'submit';
  variant?: LegacyVariant;
  size?: LegacySize;
  disabled?: boolean;
  className?: string;
}

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
