import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../../stores/authStore';

interface HealthResponse {
  features?: { auth?: boolean };
}

export function AuthInitBanner() {
  const [show, setShow] = useState(false);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const navigate = useNavigate();

  useEffect(() => {
    if (isAuthenticated) return;

    let cancelled = false;
    fetch('/api/health')
      .then((r) => r.json())
      .then((data: HealthResponse) => {
        if (!cancelled && data.features?.auth === false) {
          setShow(true);
        }
      })
      .catch(() => {});

    return () => { cancelled = true; };
  }, [isAuthenticated]);

  if (!show) return null;

  return (
    <div className="fixed top-0 left-0 right-0 z-50 bg-yellow-500/10 border-b border-yellow-500/20 px-4 py-2.5 text-sm text-yellow-700 dark:text-yellow-300 flex items-center justify-between">
      <span>
        Auth is not configured. Run{' '}
        <code className="px-1.5 py-0.5 rounded bg-yellow-500/10 font-mono text-xs">
          llmwikify auth init
        </code>{' '}
        to set up authentication.
      </span>
      <button
        onClick={() => { setShow(false); navigate('/login'); }}
        className="ml-4 px-3 py-1 rounded-md bg-yellow-500/20 hover:bg-yellow-500/30 transition-colors text-xs font-medium"
      >
        Login
      </button>
    </div>
  );
}
