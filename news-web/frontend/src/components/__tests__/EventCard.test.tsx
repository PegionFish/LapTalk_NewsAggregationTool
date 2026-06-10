import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ReactFlowProvider } from '@xyflow/react';
import EventCard from '../EventCard';
import type { Article } from '../../types';

const mockArticles: Article[] = [
  { id: 1, title: 'Test article 1', source: 'Guru3D', url: '', published: '', fetched: '2026-06-09', score: 0.8, label: 'high', verified: 1, keywords: [], human_tags: [] },
  { id: 2, title: 'Test article 2', source: 'Wccftech', url: '', published: '', fetched: '2026-06-10', score: 0.7, label: 'high', verified: 1, keywords: [], human_tags: [] },
  { id: 3, title: 'Test article 3', source: 'Phoronix', url: '', published: '', fetched: '2026-06-10', score: 0.6, label: 'medium', verified: 0, keywords: [], human_tags: [] },
  { id: 4, title: 'Test article 4', source: 'TechPowerUp', url: '', published: '', fetched: '2026-06-10', score: 0.5, label: 'medium', verified: 0, keywords: [], human_tags: [] },
  { id: 5, title: 'Test article 5', source: 'Ars Technica', url: '', published: '', fetched: '2026-06-10', score: 0.9, label: 'high', verified: 1, keywords: [], human_tags: [] },
  { id: 6, title: 'Test article 6', source: 'ZDNet', url: '', published: '', fetched: '2026-06-10', score: 0.4, label: 'low', verified: 0, keywords: [], human_tags: [] },
];

describe('EventCard', () => {
  it('renders event title', () => {
    const node = { id: 'test-1', type: 'eventCard', position: { x: 0, y: 0 },
      data: { eventId: 1, title: 'Intel Nova Lake Leak', priority: 'high', articles: [mockArticles[0]] } };
    render(<ReactFlowProvider><EventCard {...node} /></ReactFlowProvider>);
    expect(screen.getByText('📦 Intel Nova Lake Leak')).toBeInTheDocument();
  });

  it('shows article count', () => {
    const node = { id: 'test-2', type: 'eventCard', position: { x: 0, y: 0 },
      data: { eventId: 2, title: 'Test Event', priority: 'medium', articles: mockArticles.slice(0, 3) } };
    render(<ReactFlowProvider><EventCard {...node} /></ReactFlowProvider>);
    expect(screen.getByText(/3 篇文章/)).toBeInTheDocument();
  });

  it('shows +N overflow for >5 articles', () => {
    const node = { id: 'test-3', type: 'eventCard', position: { x: 0, y: 0 },
      data: { eventId: 3, title: 'Big Event', priority: 'low', articles: mockArticles } };
    render(<ReactFlowProvider><EventCard {...node} /></ReactFlowProvider>);
    expect(screen.getByText('+1 篇')).toBeInTheDocument();
  });
});
