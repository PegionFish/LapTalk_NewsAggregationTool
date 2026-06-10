import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ArticleBlock from '../ArticleBlock';
import type { Article } from '../../types';

const mockArticle: Article = {
  id: 1,
  title: 'Intel Nova Lake CPU leak reveals 16-core configuration',
  source: 'Guru3D',
  url: 'https://test.com/1',
  published: '2026-06-09',
  fetched: '2026-06-09T10:00:00',
  score: 0.85,
  label: 'high',
  verified: 1,
  keywords: ['Intel', 'Nova Lake', 'CPU'],
  human_tags: [],
};

describe('ArticleBlock', () => {
  it('renders article title truncated to 60 chars', () => {
    render(<ArticleBlock article={mockArticle} />);
    expect(screen.getByText(/Intel Nova Lake CPU leak/)).toBeInTheDocument();
  });

  it('shows source name', () => {
    render(<ArticleBlock article={mockArticle} />);
    expect(screen.getByText('Guru3D')).toBeInTheDocument();
  });

  it('shows fetched date', () => {
    render(<ArticleBlock article={mockArticle} />);
    expect(screen.getByText('06-09')).toBeInTheDocument();
  });

  it('is draggable', () => {
    render(<ArticleBlock article={mockArticle} />);
    const el = screen.getByText(/Intel Nova Lake/).closest('div[draggable]');
    expect(el).toHaveAttribute('draggable', 'true');
  });
});
