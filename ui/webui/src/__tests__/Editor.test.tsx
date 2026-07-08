import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
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

function renderEditor(selectedPage: string | null = null, initialPath = '/edit') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <ToastProvider>
        <Editor selectedPage={selectedPage} onPageSelect={vi.fn()} />
      </ToastProvider>
    </MemoryRouter>,
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
      <MemoryRouter>
        <ToastProvider>
          <Editor selectedPage="Missing" onPageSelect={vi.fn()} />
        </ToastProvider>
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByText(/Failed to load page: Page not found/)).toBeInTheDocument();
    });
  });

  it('should show error toast when save fails', async () => {
    mockReadPage.mockResolvedValue({ page_name: 'Test', content: 'Hello' });
    mockWritePage.mockRejectedValue(new Error('Network error'));

    render(
      <MemoryRouter>
        <ToastProvider>
          <Editor selectedPage="Test" onPageSelect={vi.fn()} />
        </ToastProvider>
      </MemoryRouter>,
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

  it('shows dirty=true when textarea content changes', async () => {
    mockReadPage.mockResolvedValue({ page_name: 'TestPage', content: '# TestPage' });
    render(
      <MemoryRouter initialEntries={['/edit?page=TestPage']}>
        <ToastProvider>
          <Editor selectedPage="TestPage" onPageSelect={vi.fn()} />
        </ToastProvider>
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Start writing markdown/)).toBeInTheDocument();
    });

    const textarea = screen.getByPlaceholderText(/Start writing markdown/);
    fireEvent.change(textarea, { target: { value: 'Changed content' } });

    // Save button becomes enabled (disabled when not dirty)
    const saveButton = screen.getByText('Save');
    expect(saveButton).not.toBeDisabled();
    // Dirty indicator (●) appears in toolbar
    expect(document.body.textContent).toContain('●');
  });
});

describe('Editor URL-sync (Bug 2 fix)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockStatus.mockResolvedValue({
      pages_by_type: {
        root: ['PageA', 'PageB', 'PageC'],
      },
    });
    mockReadPage.mockImplementation((name: string) =>
      Promise.resolve({ page_name: name, content: '# ' + name }),
    );
  });

  function renderEditorWithSearch(search: string) {
    const initialEntries = search ? [`/edit?${search}`] : ['/edit'];
    return render(
      <MemoryRouter initialEntries={initialEntries}>
        <Routes>
          <Route path="/edit" element={<Editor onPageSelect={vi.fn()} />} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it('loads the page specified in the URL ?page= query param', async () => {
    renderEditorWithSearch('page=PageA');
    await waitFor(() => {
      expect(mockReadPage).toHaveBeenCalledWith('PageA');
    });
  });

  it('does NOT load a page when no ?page= and no selectedPage prop', async () => {
    renderEditorWithSearch('');
    await waitFor(() => {
      expect(mockStatus).toHaveBeenCalled();
    });
    expect(mockReadPage).not.toHaveBeenCalled();
  });

  it('URL takes precedence over selectedPage prop (single source of truth)', async () => {
    // URL drives selection, not the now-deprecated prop
    render(
      <MemoryRouter initialEntries={['/edit?page=PageA']}>
        <Routes>
          <Route path="/edit" element={<Editor selectedPage="PageB" onPageSelect={vi.fn()} />} />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(mockReadPage).toHaveBeenCalledWith('PageA');
    });
    expect(mockReadPage).not.toHaveBeenCalledWith('PageB');
  });
});
