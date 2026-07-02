import { useEffect, useState } from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { useAuthStore } from '../../stores/authStore';

function Loading() {
  return <div className="p-6 text-muted-foreground">Loading...</div>;
}

export function ProtectedRoute() {
  const [checking, setChecking] = useState(true);
  const token = useAuthStore((s) => s.token);
  const clearToken = useAuthStore((s) => s.clearToken);

  useEffect(() => {
    if (!token) {
      setChecking(false);
      return;
    }
    // Validate session with server.
    fetch('/api/auth/me')
      .then((r) => {
        if (!r.ok) clearToken();
      })
      .catch(() => {})
      .finally(() => setChecking(false));
  }, [token, clearToken]);

  if (checking) return <Loading />;
  if (!token) return <Navigate to="/login" replace />;
  return <Outlet />;
}
