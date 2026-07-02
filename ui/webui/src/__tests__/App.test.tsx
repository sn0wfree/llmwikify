import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from './test-utils';
import App from '../App';
import { useAuthStore } from '../stores/authStore';

vi.mock('../api', () => ({
  api: {
    wiki: {
      status: vi.fn().mockResolvedValue({ page_count: 5, is_initialized: true }),
      sinkStatus: vi.fn().mockResolvedValue({ total_entries: 0, total_sinks: 0, urgent_count: 0, sinks: [] }),
    },
    agent: {
      status: vi.fn().mockResolvedValue({ state: 'idle' }),
    },
  },
}));

vi.mock('../components/wiki/Notifications', () => ({
  Notifications: () => <div data-testid="notifications" />,
}));

vi.mock('../components/wiki/HealthStatus', () => ({
  HealthStatus: () => <div data-testid="health-status" />,
}));

vi.mock('../components/wiki/CrossWikiSearch', () => ({
  CrossWikiSearch: () => <div data-testid="cross-wiki-search" />,
}));

vi.mock('../components/wiki/WikiSelector', () => ({
  WikiSelector: () => <div data-testid="wiki-selector" />,
}));

describe('App', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Pre-populate auth store so ProtectedRoute allows access
    useAuthStore.setState({
      token: 'test-token',
      user: { username: 'test', email: 'test@test.com' },
      isAuthenticated: true,
    });
  });

  it('should render navigation', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('llmwikify')).toBeInTheDocument();
    });
  });

  it('should show Editor nav button', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('Editor')).toBeInTheDocument();
    });
  });

  it('should show Dashboard nav button', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('Dashboard')).toBeInTheDocument();
    });
  });

  it('should show Insights nav button', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('Insights')).toBeInTheDocument();
    });
  });

  it('should show Agent nav link', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('Agent')).toBeInTheDocument();
    });
  });
});
