import { describe, it, expect, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { ToastProvider, useToast } from '../components/Toast';

function TestComponent() {
  const { addToast } = useToast();
  return (
    <div>
      <button onClick={() => addToast('success', 'Operation completed')}>Success</button>
      <button onClick={() => addToast('error', 'Something went wrong')}>Error</button>
      <button onClick={() => addToast('warning', 'Be careful', 100)}>Warning</button>
      <button onClick={() => addToast('info', 'Just a note', 0)}>Persistent</button>
    </div>
  );
}

describe('Toast', () => {
  it('should render success toast', () => {
    render(
      <ToastProvider>
        <TestComponent />
      </ToastProvider>
    );

    act(() => {
      screen.getByText('Success').click();
    });

    expect(screen.getByText('Operation completed')).toBeInTheDocument();
  });

  it('should render error toast', () => {
    render(
      <ToastProvider>
        <TestComponent />
      </ToastProvider>
    );

    act(() => {
      screen.getByText('Error').click();
    });

    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
  });

  it('should render warning toast', () => {
    render(
      <ToastProvider>
        <TestComponent />
      </ToastProvider>
    );

    act(() => {
      screen.getByText('Warning').click();
    });

    expect(screen.getByText('Be careful')).toBeInTheDocument();
  });

  it('should render info toast', () => {
    render(
      <ToastProvider>
        <TestComponent />
      </ToastProvider>
    );

    act(() => {
      screen.getByText('Persistent').click();
    });

    expect(screen.getByText('Just a note')).toBeInTheDocument();
  });

  it('should auto-dismiss toast after duration', async () => {
    vi.useFakeTimers();

    render(
      <ToastProvider>
        <TestComponent />
      </ToastProvider>
    );

    act(() => {
      screen.getByText('Warning').click();
    });

    expect(screen.getByText('Be careful')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(150);
    });

    expect(screen.queryByText('Be careful')).not.toBeInTheDocument();

    vi.useRealTimers();
  });

  it('should not auto-dismiss toast with duration 0', async () => {
    vi.useFakeTimers();

    render(
      <ToastProvider>
        <TestComponent />
      </ToastProvider>
    );

    act(() => {
      screen.getByText('Persistent').click();
    });

    expect(screen.getByText('Just a note')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(10000);
    });

    expect(screen.getByText('Just a note')).toBeInTheDocument();

    vi.useRealTimers();
  });

  it('should dismiss toast on click', () => {
    render(
      <ToastProvider>
        <TestComponent />
      </ToastProvider>
    );

    act(() => {
      screen.getByText('Success').click();
    });

    expect(screen.getByText('Operation completed')).toBeInTheDocument();

    act(() => {
      screen.getByText('Operation completed').click();
    });

    expect(screen.queryByText('Operation completed')).not.toBeInTheDocument();
  });

  it('should throw error when useToast is used outside ToastProvider', () => {
    expect(() => {
      render(<TestComponent />);
    }).toThrow('useToast must be used within ToastProvider');
  });
});
