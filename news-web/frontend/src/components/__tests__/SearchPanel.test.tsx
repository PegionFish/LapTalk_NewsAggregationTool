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

  it('renders search input', async () => {
    render(<MemoryRouter><SearchPanel onSearchResults={vi.fn()} /></MemoryRouter>);
    expect(await screen.findByPlaceholderText('搜索标题或关键词...')).toBeInTheDocument();
  });

  it('renders date preset buttons', async () => {
    render(<MemoryRouter><SearchPanel onSearchResults={vi.fn()} /></MemoryRouter>);
    expect(await screen.findByText('今天')).toBeInTheDocument();
    expect(screen.getByText('3天')).toBeInTheDocument();
    expect(screen.getByText('7天')).toBeInTheDocument();
  });

  it('collapses when chevron clicked', async () => {
    render(<MemoryRouter><SearchPanel onSearchResults={vi.fn()} /></MemoryRouter>);
    const collapseBtn = await screen.findByTitle('收起面板');
    fireEvent.click(collapseBtn);
    expect(screen.queryByPlaceholderText('搜索标题或关键词...')).not.toBeInTheDocument();
  });
});
