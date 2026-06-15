import { Button } from '../ui/legacy-button';

interface EmptyStateProps {
  icon?: string;
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
  };
}

export function EmptyState({ icon = '○', title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center h-full p-6 text-center">
      <div className="text-4xl text-muted-foreground mb-3 opacity-50">{icon}</div>
      <div className="text-muted-foreground font-medium mb-1">{title}</div>
      {description && (
        <div className="text-muted-foreground text-sm max-w-xs opacity-70">{description}</div>
      )}
      {action && (
        <Button className="mt-4" onClick={action.onClick}>
          {action.label}
        </Button>
      )}
    </div>
  );
}

export function LoadingState({ message = 'Loading...' }: { message?: string }) {
  return (
    <div className="flex items-center justify-center h-full text-muted-foreground">
      {message}
    </div>
  );
}