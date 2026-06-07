import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import { Editor } from '../components/Editor';
import { ToastProvider } from '../components/Toast';

const mockSearch = vi.fn();
const mockReadPage = vi.fn();
const mockWritePage = vi.fn();

vi.mock('../api', () => ({
  api: {
    wiki: {
      search: (...args: unknown[]) => mockSearch(...args),
      readPage: (...args: unknown[]) => mockReadPage(...args),
      writePage: (...args: unknown[]) => mockWritePage(...args),
    },
  },
}));

function renderEditor() {
  return render(
    <ToastProvider>
      <Editor selectedPage={null} onPageSelect={vi.fn()} />
    </ToastProvider>
  );
}

describe('Editor', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSearch.mockResolvedValue([]);
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
    mockSearch.mockRejectedValue(new Error('Network error'));

    renderEditor();

    await waitFor(() => {
      expect(screen.getByText('无法加载文件树')).toBeInTheDocument();
    });
  });

  it('should show error toast when page load fails', async () => {
    mockReadPage.mockRejectedValue(new Error('Page not found'));

    render(
      <ToastProvider>
        <Editor selectedPage="Missing" onPageSelect={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/页面加载失败: Page not found/)).toBeInTheDocument();
    });
  });

  it('should show error toast when save fails', async () => {
    mockReadPage.mockResolvedValue({ page_name: 'Test', content: 'Hello' });
    mockWritePage.mockRejectedValue(new Error('Network error'));

    render(
      <ToastProvider>
        <Editor selectedPage="Test" onPageSelect={vi.fn()} />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Pages')).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText('Test')).toBeInTheDocument();
    });

    const saveButton = screen.getByText('Save');
    await act(async () => {
      saveButton.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(screen.getByText(/保存失败/)).toBeInTheDocument();
    });
  });

  it('should display mode toggle buttons', async () => {
    renderEditor();

    await waitFor(() => {
      expect(screen.getByText('Edit')).toBeInTheDocument();
      expect(screen.getByText('Split')).toBeInTheDocument();
      expect(screen.getByText('Preview')).toBeInTheDocument();
    });
  });
});
