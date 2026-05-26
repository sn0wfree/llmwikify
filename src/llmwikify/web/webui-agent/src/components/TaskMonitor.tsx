import { useState, useEffect } from 'react';
import { api, TaskInfo } from '../api';
import { EmptyState } from './StateViews';

export function TaskMonitor() {
  const [tasks, setTasks] = useState<TaskInfo[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadTasks();
    const interval = setInterval(loadTasks, 10000);
    return () => clearInterval(interval);
  }, []);

  const loadTasks = async () => {
    try {
      const status = await api.agent.status();
      setTasks(status.scheduler_tasks);
    } catch {
      setTasks([]);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500">
        Loading tasks...
      </div>
    );
  }

  if (tasks.length === 0) {
    return <EmptyState icon="◷" title="No tasks configured" description="Scheduled tasks will appear here" />;
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold">Task Monitor</h2>
        <button
          onClick={loadTasks}
          className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 rounded"
        >
          Refresh
        </button>
      </div>

      <div className="space-y-3">
        {tasks.map((task) => (
          <div
            key={task.name}
            className="p-4 bg-slate-800 rounded border border-slate-700"
          >
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span
                  className={`w-2 h-2 rounded-full ${
                    task.enabled ? 'bg-green-400' : 'bg-slate-500'
                  }`}
                />
                <span className="font-medium">{task.name}</span>
              </div>
              <span className="text-xs text-slate-500">{task.cron_expr}</span>
            </div>
            <p className="text-sm text-slate-400 mb-2">{task.description}</p>
            <div className="flex gap-4 text-xs text-slate-500">
              <span>Runs: {task.run_count}</span>
              {task.last_run && <span>Last: {formatTime(task.last_run)}</span>}
              {task.next_run && <span>Next: {formatTime(task.next_run)}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso;
  }
}