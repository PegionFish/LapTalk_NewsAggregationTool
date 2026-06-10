import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { type Node, type Edge } from '@xyflow/react';
import SearchPanel from '../components/SearchPanel';
import ChainCanvas from '../components/ChainCanvas';
import { api } from '../api/client';
import type { Article } from '../types';

const DRAFT_KEY = 'canvas-draft-new';  // localStorage key for unsaved chain

export default function Workspace() {
  const [searchParams] = useSearchParams();
  const chainId = searchParams.get('chain');
  const [canvasArticles, setCanvasArticles] = useState<Article[]>([]);
  const [initialNodes, setInitialNodes] = useState<Node[]>([]);
  const [initialEdges, setInitialEdges] = useState<Edge[]>([]);
  const [loading, setLoading] = useState(!!chainId);

  // Load existing chain or recover draft on mount
  useEffect(() => {
    if (chainId) {
      api.getChainTimeline(Number(chainId)).then(async data => {
        // Fetch articles for each event in parallel
        const eventDetails = await Promise.all(
          data.timeline.map(evt =>
            api.getEvent(evt.id).catch(() => ({ articles: [] }))
          )
        );
        // Transform timeline events → React Flow nodes with articles
        const nodes = data.timeline.map((evt, i) => ({
          id: `event-${evt.id}`,
          type: 'eventCard',
          position: { x: 50 + (i % 3) * 350, y: 50 + Math.floor(i / 3) * 250 },
          data: {
            eventId: evt.id,
            title: evt.title,
            priority: 'medium',
            articles: eventDetails[i]?.articles || [],
          },
        }));
        setInitialNodes(nodes);
        setInitialEdges([]);  // Edge reconstruction from relation data in Phase 2
      }).catch(() => {}).finally(() => setLoading(false));
    } else {
      // Recover unsaved draft from localStorage
      try {
        const draft = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null');
        if (draft) {
          setInitialNodes(draft.nodes || []);
          setInitialEdges(draft.edges || []);
        }
      } catch {}
    }
  }, [chainId]);

  const handleSearchResults = useCallback((articles: Article[]) => {
    setCanvasArticles(articles);  // Provide articles as fallback for non-drag environments
  }, []);

  if (loading) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-secondary)' }}>加载逻辑链...</div>;
  }

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 48px)', margin: -24 }}>
      <SearchPanel onSearchResults={handleSearchResults} />
      <ChainCanvas articles={canvasArticles} initialNodes={initialNodes} initialEdges={initialEdges} chainId={chainId} />
    </div>
  );
}
