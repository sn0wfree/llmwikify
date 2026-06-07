import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import App from '../App';

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

vi.mock('../components/Notifications', () => ({
  Notifications: () => <div data-testid="notifications" />,
}));

vi.mock('../components/HealthStatus', () => ({
  HealthStatus: () => <div data-testid="health-status" />,
}));

describe('App', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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

  it('should show Search nav button', async () => {
    render(<App />);

    await waitFor(() => {
      const buttons = screen.getAllByText('Search');
      expect(buttons.length).toBeGreaterThanOrEqual(1);
    });
  });

  it('should show Health nav button', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('Health')).toBeInTheDocument();
    });
  });

  it('should show Insights nav button', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('Insights')).toBeInTheDocument();
    });
  });

  it('should show Growth nav button', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('Growth')).toBeInTheDocument();
    });
  });

  it('should hide agent features by default', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('llmwikify')).toBeInTheDocument();
    });

    expect(screen.queryByText('Agent Chat')).not.toBeInTheDocument();
    expect(screen.queryByText('Tasks')).not.toBeInTheDocument();
    expect(screen.queryByText('Confirmations')).not.toBeInTheDocument();
  });
});
