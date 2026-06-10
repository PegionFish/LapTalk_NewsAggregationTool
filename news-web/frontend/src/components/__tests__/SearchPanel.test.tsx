import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SearchPanel from '../SearchPanel';

vi.mock('../../api/client', () => ({
  api: {
    searchArticles: vi.fn().mockResolvedValue({
      articles: [
        { id: 1, title: 'Test Article', source: 'Guru3D', url: '', published: '', fetched: '2026-06-10', score: 0.8, label: 'high', verified: 1, keywords: [], human_tags: [] },
      ],
      total: 1, page: 1, limit: 30,
    }),
  },
}));

describe('SearchPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const open = () => fireEvent.click(screen.getByText('搜索'));

  it('starts closed with a trigger button', () => {
    render(<MemoryRouter><SearchPanel onSearchResults={vi.fn()} /></MemoryRouter>);
    expect(screen.getByText('搜索')).toBeInTheDocument();
    expect(screen.queryByPlaceholderText('搜索新闻标题或关键词...')).not.toBeInTheDocument();
  });

  it('opens floating panel on trigger click and shows search input', () => {
    render(<MemoryRouter><SearchPanel onSearchResults={vi.fn()} /></MemoryRouter>);
    open();
    expect(screen.getByPlaceholderText('搜索新闻标题或关键词...')).toBeInTheDocument();
  });

  it('shows date preset buttons when open', () => {
    render(<MemoryRouter><SearchPanel onSearchResults={vi.fn()} /></MemoryRouter>);
    open();
    expect(screen.getByText('今天')).toBeInTheDocument();
    expect(screen.getByText('3天')).toBeInTheDocument();
    expect(screen.getByText('7天')).toBeInTheDocument();
  });
});
