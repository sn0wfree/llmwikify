import { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
  variant?: 'default' | 'compact';
}

export function EmptyState({
  icon, title, description, action, className, variant = 'default',
}: EmptyStateProps) {
  return (
    <div className={cn(
      'flex flex-col items-center justify-center text-center',
      variant === 'compact' ? 'py-8 px-4' : 'py-16 px-6',
      className,
    )}>
      {icon && (
        <div className={cn(
          'relative mb-4',
          variant === 'compact' ? 'scale-90' : '',
        )}>
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-primary/20 to-accent/20 border border-primary/20 flex items-center justify-center text-primary">
            {icon}
          </div>
          <div className="absolute -inset-2 rounded-3xl bg-gradient-to-br from-primary/10 to-accent/0 blur-xl -z-10" />
        </div>
      )}
      <h3 className={cn(
        'font-semibold text-foreground tracking-tight',
        variant === 'compact' ? 'text-sm' : 'text-base',
      )}>
        {title}
      </h3>
      {description && (
        <p className={cn(
          'text-muted-foreground mt-1 max-w-md',
          variant === 'compact' ? 'text-xs' : 'text-sm',
        )}>
          {description}
        </p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

interface LoadingStateProps {
  message?: string;
  hint?: string;
  className?: string;
}

export function LoadingState({ message = 'Loading…', hint, className }: LoadingStateProps) {
  return (
    <div className={cn(
      'flex flex-col items-center justify-center text-center py-12 px-6',
      className,
    )}>
      <div className="relative mb-5">
        <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-primary to-accent opacity-80 animate-pulse" />
        <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-primary/30 to-accent/30 blur-xl animate-stage-pulse" />
      </div>
      <div className="flex items-center gap-2 text-sm text-foreground">
        <span className="thinking-dots"><span /><span /><span /></span>
        <span>{message}</span>
      </div>
      {hint && (
        <p className="text-xs text-muted-foreground mt-2 max-w-md">{hint}</p>
      )}
    </div>
  );
}

interface ErrorStateProps {
  title?: string;
  message: string;
  details?: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorState({
  title = 'Something went wrong',
  message, details, onRetry, className,
}: ErrorStateProps) {
  return (
    <div className={cn(
      'flex flex-col items-center justify-center text-center py-12 px-6',
      'rounded-xl border border-destructive/30 bg-destructive/5',
      className,
    )}>
      <div className="w-12 h-12 rounded-2xl bg-destructive/15 border border-destructive/30 flex items-center justify-center text-destructive mb-4">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      </div>
      <h3 className="text-sm font-semibold text-foreground mb-1">{title}</h3>
      <p className="text-xs text-muted-foreground max-w-md">{message}</p>
      {details && (
        <pre className="mt-3 text-[10px] text-muted-foreground/70 max-w-md overflow-x-auto text-left bg-muted/40 rounded-md px-2 py-1.5 font-mono">
          {details}
        </pre>
      )}
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-4 px-3 py-1.5 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:brightness-110 transition-all"
        >
          Try again
        </button>
      )}
    </div>
  );
}
