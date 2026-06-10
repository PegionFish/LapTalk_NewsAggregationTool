import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import SearchPanel from '../SearchPanel';

// Mock the API client
vi.mock('../../api/client', () => ({
  api: {
    searchArticles: vi.fn().mockResolvedValue({
      articles: [
        { id: 1, title: 'Test Article', source: 'Guru3D', url: '', published: '', fetched: '2026-06-10', score: 0.8, label: 'high', verified: 1, keywords: [], human_tags: [] },
      ],
      total: 1,
      page: 1,
      limit: 30,
    }),
  },
}));

describe('SearchPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders search input', () => {
    render(<SearchPanel onSearchResults={vi.fn()} />);
    expect(screen.getByPlaceholderText('搜索新闻...')).toBeInTheDocument();
  });

  it('renders date preset buttons', () => {
    render(<SearchPanel onSearchResults={vi.fn()} />);
    expect(screen.getByText('今天')).toBeInTheDocument();
    expect(screen.getByText('3天')).toBeInTheDocument();
    expect(screen.getByText('7天')).toBeInTheDocument();
  });

  it('shows collapsed state when toggle clicked', () => {
    render(<SearchPanel onSearchResults={vi.fn()} />);
    fireEvent.click(screen.getByText('◀ 收起'));
    // After collapse, only the expand button should be visible
    expect(screen.queryByPlaceholderText('搜索新闻...')).not.toBeInTheDocument();
  });
});
