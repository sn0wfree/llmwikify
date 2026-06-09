import { Textarea } from './textarea';
import { cn } from '@/lib/utils';

interface LegacyInputProps {
  value?: string;
  onChange?: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  onKeyDown?: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  placeholder?: string;
  className?: string;
}

export function Input({ className, ...props }: LegacyInputProps) {
  return (
    <Textarea
      className={cn('min-h-[36px] max-h-[120px]', className)}
      {...props}
    />
  );
}
