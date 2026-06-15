import { useState, useEffect } from 'react';
import { api, TaskInfo } from '../../api';
import { useWikiStore } from '../../stores/wikiStore';
import { EmptyState } from '../agent/StateViews';
import { Card } from '../ui/legacy-card';
import { Button } from '../ui/legacy-button';
import { Badge } from '../ui/legacy-badge';

export function TaskMonitor() {
  const [tasks, setTasks] = useState<TaskInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const { currentWikiId } = useWikiStore();

  useEffect(() => {
    loadTasks();
    const interval = setInterval(loadTasks, 10000);
    return () => clearInterval(interval);
  }, []);

  const loadTasks = async () => {
    try {
      const status = await api.agent.status(currentWikiId || undefined);
      setTasks(status.scheduler_tasks);
    } catch {
      setTasks([]);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
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
        <h2 className="text-xl font-bold text-foreground">Task Monitor</h2>
        <Button variant="secondary" size="sm" onClick={loadTasks}>
          Refresh
        </Button>
      </div>

      <div className="space-y-3">
        {tasks.map((task) => (
          <Card key={task.name} variant="bordered" padding="md">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span
                  className={`w-2 h-2 rounded-full ${
                    task.enabled ? 'bg-green-400' : 'bg-muted'
                  }`}
                />
                <span className="font-medium text-foreground">{task.name}</span>
              </div>
              <span className="text-xs text-muted-foreground">{task.cron_expr}</span>
            </div>
            <p className="text-sm text-muted-foreground mb-2">{task.description}</p>
            <div className="flex gap-4 text-xs text-muted-foreground">
              <span>Runs: {task.run_count}</span>
              {task.last_run && <span>Last: {formatTime(task.last_run)}</span>}
              {task.next_run && <span>Next: {formatTime(task.next_run)}</span>}
            </div>
          </Card>
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