import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { DreamProposals } from '../components/DreamProposals';

const mockProposals = vi.fn();
const mockApprove = vi.fn();
const mockReject = vi.fn();

vi.mock('../api', () => ({
  api: {
    dream: {
      proposals: () => mockProposals(),
      approve: (...args: unknown[]) => mockApprove(...args),
      reject: (...args: unknown[]) => mockReject(...args),
    },
  },
}));

describe('DreamProposals', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should show loading state initially', () => {
    mockProposals.mockReturnValue(new Promise(() => {}));
    render(<DreamProposals />);
    expect(screen.getByText('Loading proposals...')).toBeInTheDocument();
  });

  it('should render empty state when no proposals', async () => {
    mockProposals.mockResolvedValue({ proposals: {}, stats: {} });
    render(<DreamProposals />);

    await waitFor(() => {
      expect(screen.getByText('No pending dream proposals.')).toBeInTheDocument();
    });
  });

  it('should render proposal items', async () => {
    mockProposals.mockResolvedValue({
      proposals: {
        'Test Page': [{
          id: 'p1',
          page_name: 'Test Page',
          edit_type: 'append',
          content: 'New content',
          reason: 'Test reason',
          content_length: 11,
          status: 'pending',
          created_at: '2024-01-01T00:00:00Z',
          reviewed_at: null,
        }],
      },
      stats: { pending: 1, auto_approved: 0 },
    });

    render(<DreamProposals />);

    await waitFor(() => {
      expect(screen.getByText('Test Page')).toBeInTheDocument();
    });
  });
});
