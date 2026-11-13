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
    // Validate the localStorage JWT with the server (P1-7): send it as
    // Bearer and clear when the server says the session is gone.
    fetch('/api/auth/me', {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (r) => {
        if (!r.ok) {
          clearToken();
          return;
        }
        try {
          const data = await r.json();
          if (data && data.authenticated === false) clearToken();
        } catch {
          clearToken();
        }
      })
      .catch(() => {})
      .finally(() => setChecking(false));
  }, [token, clearToken]);

  if (checking) return <Loading />;
  if (!token) return <Navigate to="/login" replace />;
  return <Outlet />;
}
