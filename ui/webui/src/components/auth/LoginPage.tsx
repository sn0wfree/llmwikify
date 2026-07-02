import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../../stores/authStore';
import type { AuthError } from '../../types/auth';

const API_BASE = '/api';

type Tab = 'token' | 'register';

export function LoginPage() {
  const [tab, setTab] = useState<Tab>('token');
  const [email, setEmail] = useState('');
  const [pat, setPat] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const login = useAuthStore((s) => s.login);
  const navigate = useNavigate();

  const handleTokenSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/auth/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pat: pat.trim() }),
      });
      if (!res.ok) {
        let msg = `Verification failed (${res.status})`;
        try {
          const body: AuthError = await res.json();
          msg = body.detail || body.error || msg;
        } catch { /* non-JSON */ }
        setError(msg);
        setLoading(false);
        return;
      }
      const data = await res.json();
      login(data.access_token, data.user);
      navigate('/', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error');
      setLoading(false);
    }
  };

  const handleRegisterSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim() }),
      });
      if (!res.ok) {
        let msg = `Registration failed (${res.status})`;
        try {
          const body: AuthError = await res.json();
          msg = body.detail || body.error || msg;
        } catch { /* non-JSON */ }
        setError(msg);
        setLoading(false);
        return;
      }
      const data = await res.json();
      // PAT is returned once — store in localStorage for immediate use.
      login(data.access_token, data.user);
      // Also store the PAT for future sessions.
      if (data.pat) {
        localStorage.setItem('llmwikify_pat', data.pat);
      }
      navigate('/', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error');
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="w-full max-w-sm p-8 rounded-xl glass-strong border border-border/50">
        <h1 className="text-xl font-semibold text-foreground text-center mb-6">
          llmwikify
        </h1>

        {/* Tab switcher */}
        <div className="flex mb-6 border border-border/50 rounded-lg overflow-hidden">
          <button
            onClick={() => { setTab('token'); setError(''); }}
            className={`flex-1 py-2 text-sm font-medium transition-colors ${
              tab === 'token'
                ? 'bg-primary/10 text-primary'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            Paste Token
          </button>
          <button
            onClick={() => { setTab('register'); setError(''); }}
            className={`flex-1 py-2 text-sm font-medium transition-colors ${
              tab === 'register'
                ? 'bg-primary/10 text-primary'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            Create Account
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-sm text-destructive">
            {error}
          </div>
        )}

        {tab === 'token' ? (
          <form onSubmit={handleTokenSubmit} className="space-y-4">
            <div>
              <label htmlFor="pat" className="block text-sm font-medium text-foreground mb-1.5">
                Personal Access Token
              </label>
              <input
                id="pat"
                type="text"
                value={pat}
                onChange={(e) => setPat(e.target.value)}
                required
                autoFocus
                className="w-full px-3 py-2 rounded-lg bg-background border border-border/50 text-foreground text-sm font-mono placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50"
                placeholder="llmw_..."
              />
              <p className="mt-1.5 text-xs text-muted-foreground">
                Get a token via CLI: <code className="px-1 py-0.5 rounded bg-muted text-[10px]">llmwikify auth create-token</code>
              </p>
            </div>
            <button
              type="submit"
              disabled={loading || !pat.trim()}
              className="w-full py-2.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? 'Verifying...' : 'Sign in'}
            </button>
          </form>
        ) : (
          <form onSubmit={handleRegisterSubmit} className="space-y-4">
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-foreground mb-1.5">
                Email
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
                autoComplete="email"
                className="w-full px-3 py-2 rounded-lg bg-background border border-border/50 text-foreground text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50"
                placeholder="you@example.com"
              />
              <p className="mt-1.5 text-xs text-muted-foreground">
                No password needed. You'll get a token instantly.
              </p>
            </div>
            <button
              type="submit"
              disabled={loading || !email.trim()}
              className="w-full py-2.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? 'Creating...' : 'Create account'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
