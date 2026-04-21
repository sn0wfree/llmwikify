import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { IngestLog } from '../components/IngestLog';

const mockLog = vi.fn();

vi.mock('../api', () => ({
  api: {
    ingest: {
      log: () => mockLog(),
    },
  },
}));

describe('IngestLog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should show loading state initially', () => {
    mockLog.mockReturnValue(new Promise(() => {}));
    render(<IngestLog />);
    expect(screen.getByText('Loading ingest log...')).toBeInTheDocument();
  });

  it('should render empty state when no entries', async () => {
    mockLog.mockResolvedValue([]);
    render(<IngestLog />);

    await waitFor(() => {
      expect(screen.getByText('No ingest records.')).toBeInTheDocument();
    });
  });

  it('should render log entries', async () => {
    mockLog.mockResolvedValue([{
      id: 'e1',
      tool: 'wiki_ingest',
      arguments: { source: 'test.pdf' },
      result_summary: 'Ingested successfully',
      timestamp: '2024-01-01T00:00:00Z',
      status: 'success',
    }]);

    render(<IngestLog />);

    await waitFor(() => {
      expect(screen.getByText('Ingest History')).toBeInTheDocument();
    });
  });
});
