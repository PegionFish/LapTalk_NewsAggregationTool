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

  // Relation type → visual style mapping
  const RELATION_STYLES: Record<string, { stroke: string; dash: string }> = {
    before:  { stroke: '#81c784', dash: '' },       // green solid
    after:   { stroke: '#4fc3f7', dash: '' },       // blue solid
    update:  { stroke: '#ffb74d', dash: '' },       // orange solid
    spawn:   { stroke: '#ce93d8', dash: '' },       // purple solid
    related: { stroke: '#888',    dash: '5,5' },    // gray dashed
  };

  // Load existing chain or recover draft on mount
  useEffect(() => {
    if (chainId) {
      api.getChainTimeline(Number(chainId)).then(async data => {
        const eventIds = data.timeline.map(evt => evt.id);

        // Fetch articles for each event in parallel
        const eventDetails = await Promise.all(
          eventIds.map(id =>
            api.getEvent(id).catch(() => ({ articles: [] }))
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

        // Reconstruct edges from event_relations table
        let edges: Edge[] = [];
        if (eventIds.length >= 2) {
          try {
            const relData = await api.getRelationsBetween(eventIds);
            edges = relData.relations.map((rel, idx) => {
              const style = RELATION_STYLES[rel.relation] || RELATION_STYLES['related'];
              const isAuto = rel.created_by === 'auto';
              return {
                id: `re-${rel.from_event_id}-${rel.to_event_id}-${idx}`,
                source: `event-${rel.from_event_id}`,
                target: `event-${rel.to_event_id}`,
                label: rel.relation,
                style: {
                  stroke: style.stroke,
                  strokeWidth: 2,
                  strokeDasharray: isAuto ? '5,5' : style.dash,
                },
                labelStyle: { fill: style.stroke, fontSize: 10 },
                animated: isAuto,
              } as Edge;
            });
          } catch {}
        }

        setInitialNodes(nodes);
        setInitialEdges(edges);
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
