import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent } from '@testing-library/react';
import { render, screen, act, waitFor } from './test-utils';
import { Editor } from '../components/wiki/Editor';
import { ToastProvider } from '../components/wiki/Toast';

const mockStatus = vi.fn();
const mockReadPage = vi.fn();
const mockWritePage = vi.fn();

vi.mock('../api', () => ({
  api: {
    wiki: {
      status: (...args: unknown[]) => mockStatus(...args),
      readPage: (...args: unknown[]) => mockReadPage(...args),
      writePage: (...args: unknown[]) => mockWritePage(...args),
      graph: vi.fn().mockResolvedValue({ nodes: [], edges: [], all_types: [] }),
    },
  },
}));

function renderEditor(selectedPage: string | null = null) {
  return render(
    <ToastProvider>
      <Editor selectedPage={selectedPage} onPageSelect={vi.fn()} />
    </ToastProvider>
  );
}

describe('Editor', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockStatus.mockResolvedValue({ pages_by_type: {} });
    mockReadPage.mockResolvedValue({ page_name: 'Test', content: 'Hello' });
    mockWritePage.mockResolvedValue({ message: 'OK' });
  });

  it('should render editor component', async () => {
    renderEditor();
    await waitFor(() => {
      expect(screen.getByText('Pages')).toBeInTheDocument();
    });
  });

  it('should show warning toast when file tree fails to load', async () => {
    mockStatus.mockRejectedValue(new Error('Network error'));
    renderEditor();
    await waitFor(() => {
      expect(screen.getByText('Could not load page tree')).toBeInTheDocument();
    });
  });

  it('should show error toast when page load fails', async () => {
    mockReadPage.mockRejectedValue(new Error('Page not found'));
    render(
      <ToastProvider>
        <Editor selectedPage="Missing" onPageSelect={vi.fn()} />
      </ToastProvider>,
    );
    await waitFor(() => {
      expect(screen.getByText(/Failed to load page: Page not found/)).toBeInTheDocument();
    });
  });

  it('should show error toast when save fails', async () => {
    mockReadPage.mockResolvedValue({ page_name: 'Test', content: 'Hello' });
    mockWritePage.mockRejectedValue(new Error('Network error'));

    render(
      <ToastProvider>
        <Editor selectedPage="Test" onPageSelect={vi.fn()} />
      </ToastProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('Pages')).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByText('Test')).toBeInTheDocument();
    });

    const saveButton = screen.getByText('Save');
    // Trigger dirty=true so the Save button is enabled (button is disabled when !dirty).
    const textarea = screen.getByPlaceholderText(/Start writing markdown/);
    fireEvent.change(textarea, { target: { value: 'Changed content' } });

    await act(async () => {
      saveButton.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(screen.getByText(/Save failed/)).toBeInTheDocument();
    });
  });

  it('should display mode toggle buttons', async () => {
    renderEditor();
    await waitFor(() => {
      expect(screen.getAllByText(/Edit/i).length).toBeGreaterThan(0);
    });
    // Three mode buttons: Edit, Graph, Preview
    expect(screen.getByText('Graph')).toBeInTheDocument();
    expect(screen.getByText('Preview')).toBeInTheDocument();
  });
});
