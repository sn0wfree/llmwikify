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
      <div className="text-4xl text-slate-600 mb-3">{icon}</div>
      <div className="text-slate-400 font-medium mb-1">{title}</div>
      {description && (
        <div className="text-slate-500 text-sm max-w-xs">{description}</div>
      )}
      {action && (
        <button
          onClick={action.onClick}
          className="mt-4 px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 rounded text-white"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}

export function LoadingState({ message = 'Loading...' }: { message?: string }) {
  return (
    <div className="flex items-center justify-center h-full text-slate-500">
      {message}
    </div>
  );
}