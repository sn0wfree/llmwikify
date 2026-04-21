import { useState, useEffect } from 'react';
import { api, Notification } from '../api';

export function Notifications() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);

  const unread = notifications.filter((n) => !n.read).length;

  useEffect(() => {
    loadNotifications();
    const interval = setInterval(loadNotifications, 15000);
    return () => clearInterval(interval);
  }, []);

  const loadNotifications = async () => {
    try {
      const list = await api.notifications.list();
      setNotifications(list);
    } catch {
      // No agent endpoint
    }
  };

  const markRead = async (id: string) => {
    try {
      await api.notifications.markRead(id);
      setNotifications((prev) =>
        prev.map((n) => (n.id === id ? { ...n, read: true } : n))
      );
    } catch {
      // Ignore
    }
  };

  return (
    <div className="relative">
      <button
        onClick={() => setShowDropdown(!showDropdown)}
        className="relative p-1.5 rounded hover:bg-slate-700 text-slate-400"
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
          />
        </svg>
        {unread > 0 && (
          <span className="absolute -top-1 -right-1 w-4 h-4 bg-red-500 rounded-full text-xs text-white flex items-center justify-center">
            {unread}
          </span>
        )}
      </button>

      {showDropdown && (
        <div className="absolute right-0 top-full mt-2 w-80 bg-slate-800 border border-slate-700 rounded-lg shadow-xl z-50">
          <div className="p-3 border-b border-slate-700">
            <h3 className="text-sm font-semibold">Notifications</h3>
          </div>
          <div className="max-h-64 overflow-y-auto">
            {notifications.length === 0 ? (
              <p className="p-4 text-sm text-slate-500 text-center">No notifications</p>
            ) : (
              notifications.map((n) => (
                <div
                  key={n.id}
                  onClick={() => markRead(n.id)}
                  className={`p-3 border-b border-slate-700/50 cursor-pointer hover:bg-slate-700/50 ${
                    !n.read ? 'bg-slate-700/30' : ''
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <NotificationIcon type={n.type} />
                    <span className="text-sm">{n.message}</span>
                  </div>
                  <span className="text-xs text-slate-500 mt-1 block">
                    {formatTime(n.timestamp)}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function NotificationIcon({ type }: { type: string }) {
  const colors: Record<string, string> = {
    info: 'text-blue-400',
    success: 'text-green-400',
    warning: 'text-amber-400',
    error: 'text-red-400',
  };
  return (
    <span className={`w-2 h-2 rounded-full ${colors[type] || colors.info}`} />
  );
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    return d.toLocaleTimeString();
  } catch {
    return '';
  }
}
