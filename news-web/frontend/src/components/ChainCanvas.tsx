import { useCallback, useRef, useState, useEffect } from 'react';
import {
  ReactFlow, addEdge, useNodesState, useEdgesState, Controls, Background,
  type Connection, type Edge, type Node,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import EventCard from './EventCard';
import RelationDialog from './RelationDialog';
import { api } from '../api/client';
import type { Article } from '../types';

// Use a plain object for nodeTypes to avoid TS issues with xyflow v12
const nodeTypes = { eventCard: EventCard as (props: Record<string, unknown>) => JSX.Element };

interface Props {
  articles: Article[];
  initialNodes?: Node[];
  initialEdges?: Edge[];
  chainId?: string | null;
}

let nodeIdCounter = 0;
const nextNodeId = () => `event-${++nodeIdCounter}`;

const DRAFT_KEY = 'canvas-draft-new';

export default function ChainCanvas({ articles, initialNodes = [], initialEdges = [], chainId }: Props) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(initialEdges);
  const [relationDialog, setRelationDialog] = useState<{ from: string; to: string } | null>(null);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);

  const onDrop = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    const json = event.dataTransfer.getData('application/json');
    if (!json) return;
    const data = JSON.parse(json);
    if (data.type !== 'article') return;

    const article: Article = data.article;
    const eventName = article.event?.title || '未分类';

    // Check if node for this event already exists
    const existing = nodes.find(n => n.data?.eventId === article.event?.id);
    if (existing) {
      setNodes(nds => nds.map(n => {
        if (n.id === existing.id) {
          const arts = [...((n.data?.articles as Article[]) || []), article];
          const deduped = arts.filter((a: Article, i: number, arr: Article[]) => arr.findIndex(x => x.id === a.id) === i);
          return { ...n, data: { ...n.data, articles: deduped } };
        }
        return n;
      }));
      return;
    }

    // Create new event node
    const position = reactFlowWrapper.current
      ? { x: event.clientX - 150, y: event.clientY - 50 }
      : { x: Math.random() * 300, y: Math.random() * 300 };

    const newNode: Node = {
      id: nextNodeId(),
      type: 'eventCard',
      position,
      data: {
        eventId: article.event?.id || 0,
        title: eventName,
        priority: article.label || 'medium',
        articles: [article],
      },
    };
    setNodes(nds => [...nds, newNode]);
  }, [nodes, setNodes]);

  const onDragOver = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const onConnect = useCallback((connection: Connection) => {
    if (connection.source && connection.target) {
      setRelationDialog({ from: connection.source.toString(), to: connection.target.toString() });
    }
  }, []);

  const handleRelationSelect = useCallback(async (relation: string) => {
    if (!relationDialog) return;
    setEdges(eds => addEdge({
      id: `e-${relationDialog.from}-${relationDialog.to}-${Date.now()}`,
      source: relationDialog.from,
      target: relationDialog.to,
      label: relation,
      style: { stroke: '#4fc3f7', strokeWidth: 2 },
      labelStyle: { fill: '#4fc3f7', fontSize: 10 },
      animated: true,
    }, eds));
    setRelationDialog(null);
  }, [relationDialog, setEdges]);

  // ── Auto-save draft to localStorage (debounced 2s) ──
  const saveTimer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => {
    if (chainId) return;
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({ nodes, edges }));
    }, 2000);
    return () => clearTimeout(saveTimer.current);
  }, [nodes, edges, chainId]);

  const handleCreateChain = useCallback(async () => {
    const title = prompt('请输入逻辑链标题:', '新建逻辑链');
    if (!title) return;
    const eventIds = nodes
      .map(n => n.data?.eventId as number | undefined)
      .filter((id): id is number => id != null && id > 0);
    try {
      await api.createChain({ title, event_ids: eventIds });
      alert('逻辑链创建成功');
    } catch (e) {
      alert('创建失败: ' + (e as Error).message);
    }
  }, [nodes]);

  return (
    <div ref={reactFlowWrapper} style={{ flex: 1, position: 'relative' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onDrop={onDrop}
        onDragOver={onDragOver}
        nodeTypes={nodeTypes}
        fitView
        style={{ background: 'var(--bg-primary)' }}
      >
        <Controls />
        <Background color="#2a2a3e" gap={20} />
      </ReactFlow>

      {nodes.length > 0 && (
        <button onClick={handleCreateChain}
          style={{ position: 'absolute', top: 12, right: 12, background: 'var(--accent)', border: 'none', borderRadius: 6, padding: '8px 16px', color: '#000', fontWeight: 'bold', fontSize: 13, cursor: 'pointer', zIndex: 10 }}>
          ➕ 创建逻辑链
        </button>
      )}

      <RelationDialog open={!!relationDialog} onClose={() => setRelationDialog(null)} onSelect={handleRelationSelect} />
    </div>
  );
}
