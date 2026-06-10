import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ReactFlowProvider } from '@xyflow/react';
import { MemoryRouter } from 'react-router-dom';
import EventCard from '../EventCard';
import type { Article } from '../../types';

const base = { content_lang: 'en', ai_analyzed: false, human_processed: false, has_translation: false } as const;
const mockArticles: Article[] = [
  { id: 1, title: 'Test article 1', source: 'Guru3D', url: '', published: '', fetched: '2026-06-09', score: 0.8, label: 'high', verified: 1, keywords: [], human_tags: [], content_status: 'fetched', ...base },
  { id: 2, title: 'Test article 2', source: 'Wccftech', url: '', published: '', fetched: '2026-06-10', score: 0.7, label: 'high', verified: 1, keywords: [], human_tags: [], content_status: 'fetched', ...base },
  { id: 3, title: 'Test article 3', source: 'Phoronix', url: '', published: '', fetched: '2026-06-10', score: 0.6, label: 'medium', verified: 0, keywords: [], human_tags: [], content_status: 'pending', ...base },
  { id: 4, title: 'Test article 4', source: 'TechPowerUp', url: '', published: '', fetched: '2026-06-10', score: 0.5, label: 'medium', verified: 0, keywords: [], human_tags: [], content_status: 'pending', ...base },
  { id: 5, title: 'Test article 5', source: 'Ars Technica', url: '', published: '', fetched: '2026-06-10', score: 0.9, label: 'high', verified: 1, keywords: [], human_tags: [], content_status: 'fetched', ...base },
  { id: 6, title: 'Test article 6', source: 'ZDNet', url: '', published: '', fetched: '2026-06-10', score: 0.4, label: 'low', verified: 0, keywords: [], human_tags: [], content_status: 'pending', ...base },
];

function TestWrapper({ children }: { children: React.ReactNode }) {
  return <MemoryRouter><ReactFlowProvider>{children}</ReactFlowProvider></MemoryRouter>;
}

describe('EventCard', () => {
  it('renders event title', () => {
    const Card = EventCard as unknown as React.FC<{ data: { eventId: number; title: string; priority: string; articles: Article[] } }>;
    render(<TestWrapper><Card data={{ eventId: 1, title: 'Intel Nova Lake Leak', priority: 'high', articles: [mockArticles[0]] }} /></TestWrapper>);
    expect(screen.getByText('📦 Intel Nova Lake Leak')).toBeInTheDocument();
  });

  it('shows article count', () => {
    const Card = EventCard as unknown as React.FC<{ data: { eventId: number; title: string; priority: string; articles: Article[] } }>;
    render(<TestWrapper><Card data={{ eventId: 2, title: 'Test Event', priority: 'medium', articles: mockArticles.slice(0, 3) }} /></TestWrapper>);
    expect(screen.getByText(/3 篇文章/)).toBeInTheDocument();
  });

  it('shows +N overflow for >5 articles', () => {
    const Card = EventCard as unknown as React.FC<{ data: { eventId: number; title: string; priority: string; articles: Article[] } }>;
    render(<TestWrapper><Card data={{ eventId: 3, title: 'Big Event', priority: 'low', articles: mockArticles }} /></TestWrapper>);
    expect(screen.getByText('+1 篇')).toBeInTheDocument();
  });
});
