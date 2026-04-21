import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { EditHistory } from '../components/EditHistory';

const mockStatus = vi.fn();

vi.mock('../api', () => ({
  api: {
    agent: {
      status: () => mockStatus(),
    },
  },
}));

describe('EditHistory', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should show loading state initially', () => {
    mockStatus.mockReturnValue(new Promise(() => {}));
    render(<EditHistory />);
    expect(screen.getByText('Loading edit history...')).toBeInTheDocument();
  });

  it('should render empty state when no edits', async () => {
    mockStatus.mockResolvedValue({ action_log: [] });
    render(<EditHistory />);

    await waitFor(() => {
      expect(screen.getByText('No edit history.')).toBeInTheDocument();
    });
  });

  it('should render edit entries', async () => {
    mockStatus.mockResolvedValue({
      action_log: [{
        tool: 'wiki_write_page',
        success: true,
        error: null,
        confirmation_id: null,
        timestamp: '2024-01-01T00:00:00Z',
      }],
    });

    render(<EditHistory />);

    await waitFor(() => {
      expect(screen.getByText('Edit History')).toBeInTheDocument();
    });
  });
});
