/**
 * PPTSidebar — Task History Sidebar (v0.5)
 *
 * Lists past PPT tasks from the backend, polls every 5s for updates.
 * Uses useUrlTask hook so selection state lives in URL hash (no React
 * state prop drilling between sidebar and PPTGenerator).
 *
 * Pattern follows SessionSidebar for UI consistency.
 */
import { useState, useEffect } from 'react';
import {
  listTasks,
  deleteTask,
  PPTTaskSummary,
  SourceType,
} from '../lib/ppt-api';
import { useUrlTask } from '../lib/useUrlTask';

type FilterType = 'all' | SourceType;

const FILTER_LABELS: Record<FilterType, string> = {
  all: '全部',
  topic: '主题',
  research: '研究',
  chat: '对话',
};

const STATUS_LABELS: Record<string, { icon: string; color: string; text: string }> = {
  done: { icon: '✓', color: 'text-green-400', text: '已完成' },
  running: { icon: '⟳', color: 'text-blue-400 animate-spin', text: '生成中' },
  pending: { icon: '⏳', color: 'text-yellow-400', text: '排队中' },
  error: { icon: '✗', color: 'text-red-400', text: '失败' },
};

function formatDate(iso: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    if (diff < 60000) return '刚刚';
    if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`;
    if (diff < 604800000) return `${Math.floor(diff / 86400000)} 天前`;
    return d.toLocaleDateString();
  } catch {
    return '';
  }
}

export function PPTSidebar() {
  const [taskId, setTaskId] = useUrlTask();
  const [tasks, setTasks] = useState<PPTTaskSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<FilterType>('all');

  useEffect(() => {
    let mounted = true;
    const fetchTasks = async () => {
      try {
        const data = await listTasks(50, filter === 'all' ? undefined : filter);
        if (mounted) {
          setTasks(data.tasks);
          setLoading(false);
        }
      } catch (e) {
        if (mounted) {
          setTasks([]);
          setLoading(false);
        }
      }
    };
    fetchTasks();
    const i = setInterval(fetchTasks, 5000);
    return () => {
      mounted = false;
      clearInterval(i);
    };
  }, [filter]);

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    try {
      await deleteTask(id);
      setTasks((prev) => prev.filter((t) => t.id !== id));
      // If we deleted the active task, clear the URL hash
      if (taskId === id) {
        setTaskId(null);
      }
    } catch {
      /* silent */
    }
  };

  const handleSelect = (id: string) => {
    setTaskId(id);
  };

  const handleNew = () => {
    setTaskId(null);
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header: New task button */}
      <div className="p-3 border-b border-[var(--border)]">
        <button
          onClick={handleNew}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded text-sm font-medium
            bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] transition-colors"
        >
          <span>＋</span>
          <span>新建演示文稿</span>
        </button>
      </div>

      {/* Filter tabs */}
      <div className="px-2 py-2 border-b border-[var(--border)] flex gap-1 text-xs">
        {(Object.keys(FILTER_LABELS) as FilterType[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-2 py-1 rounded transition-colors
              ${filter === f
                ? 'bg-[var(--accent)]/15 text-[var(--accent)] font-medium'
                : 'text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]'
              }`}
          >
            {FILTER_LABELS[f]}
          </button>
        ))}
      </div>

      {/* Task list */}
      <div className="flex-1 overflow-y-auto">
        {loading && tasks.length === 0 && (
          <div className="p-3 text-xs text-[var(--text-secondary)] text-center">
            加载中...
          </div>
        )}
        {!loading && tasks.length === 0 && (
          <div className="p-3 text-xs text-[var(--text-secondary)] text-center">
            暂无任务
            <div className="mt-1 text-[10px] opacity-70">点上方"新建"开始</div>
          </div>
        )}
        {tasks.map((task) => {
          const status = STATUS_LABELS[task.status] || STATUS_LABELS.pending;
          return (
            <div
              key={task.id}
              onClick={() => handleSelect(task.id)}
              className={`
                group relative px-3 py-2.5 cursor-pointer border-b border-[var(--border)] transition-colors
                ${task.id === taskId
                  ? 'bg-[var(--accent)]/10 border-l-2 border-l-[var(--accent)]'
                  : 'hover:bg-[var(--bg-tertiary)]'
                }
              `}
              title={task.title || '(未命名)'}
            >
              <div className="flex items-start gap-2">
                <span className={`text-sm flex-shrink-0 ${status.color}`}>
                  {status.icon}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate text-[var(--text-primary)]">
                    {task.title || '(未命名)'}
                  </div>
                  <div className="text-xs text-[var(--text-secondary)] mt-0.5 flex items-center gap-1.5 flex-wrap">
                    <span>{task.slide_count} 页</span>
                    <span>·</span>
                    <span>{task.theme}</span>
                    <span>·</span>
                    <span>{formatDate(task.updated_at)}</span>
                  </div>
                  {task.status === 'error' && task.error && (
                    <div className="text-xs text-red-400 mt-1 truncate" title={task.error}>
                      ⚠ {task.error}
                    </div>
                  )}
                </div>
              </div>
              <button
                onClick={(e) => handleDelete(e, task.id)}
                className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100
                  text-base text-[var(--text-secondary)] hover:text-red-400 transition-opacity p-1 leading-none"
                title="删除任务"
              >
                ×
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
