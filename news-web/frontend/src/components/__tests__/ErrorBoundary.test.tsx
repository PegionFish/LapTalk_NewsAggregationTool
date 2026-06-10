import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Component, type ReactNode } from 'react';

// Duplicate ErrorBoundary here to test in isolation (avoids router dep)
class ErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean; error: Error | null }> {
  state = { hasError: false, error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }
  render() {
    if (this.state.hasError) {
      return (
        <div>
          <h2 data-testid="error-title">页面出现异常</h2>
          <p data-testid="error-message">{this.state.error?.message}</p>
          <button data-testid="reload-btn" onClick={() => { this.setState({ hasError: false, error: null }); }}>
            重新加载
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

function ThrowError({ msg }: { msg: string }) {
  throw new Error(msg);
  return null;
}

describe('ErrorBoundary', () => {
  it('renders children when no error', () => {
    render(
      <ErrorBoundary>
        <div data-testid="child">Hello</div>
      </ErrorBoundary>
    );
    expect(screen.getByTestId('child')).toHaveTextContent('Hello');
  });

  it('shows error UI when child throws', () => {
    // Suppress console.error for this test
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <ThrowError msg="Test crash" />
      </ErrorBoundary>
    );
    expect(screen.getByTestId('error-title')).toBeInTheDocument();
    expect(screen.getByTestId('error-message')).toHaveTextContent('Test crash');
    expect(screen.getByTestId('reload-btn')).toBeInTheDocument();
    spy.mockRestore();
  });
});
