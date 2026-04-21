import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { Confirmations } from '../components/Confirmations';

const mockList = vi.fn();
const mockApprove = vi.fn();
const mockReject = vi.fn();

vi.mock('../api', () => ({
  api: {
    confirmations: {
      list: () => mockList(),
      approve: (...args: unknown[]) => mockApprove(...args),
      reject: (...args: unknown[]) => mockReject(...args),
    },
  },
}));

describe('Confirmations', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should show loading state initially', () => {
    mockList.mockReturnValue(new Promise(() => {}));
    render(<Confirmations />);
    expect(screen.getByText('Loading confirmations...')).toBeInTheDocument();
  });

  it('should render empty state when no confirmations', async () => {
    mockList.mockResolvedValue({});
    render(<Confirmations />);

    await waitFor(() => {
      expect(screen.getByText('No pending confirmations.')).toBeInTheDocument();
    });
  });

  it('should render confirmation items', async () => {
    mockList.mockResolvedValue({
      write: [{
        id: 'c1',
        tool: 'wiki_write_page',
        arguments: { page_name: 'Test', content: 'Hello' },
        action_type: 'write',
        impact: { page: 'Test', chars: 5 },
        group: 'write',
        created_at: '2024-01-01T00:00:00Z',
        status: 'pending',
      }],
    });

    render(<Confirmations />);

    await waitFor(() => {
      expect(screen.getByText('wiki_write_page')).toBeInTheDocument();
    });
  });
});
