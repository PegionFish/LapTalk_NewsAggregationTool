import { useCallback, useRef, useState, useEffect } from 'react';
import {
  ReactFlow, addEdge, useNodesState, useEdgesState, Controls, Background,
  type Connection, type Edge, type Node, type OnNodesChange, type OnEdgesChange,
  type NodeChange, type EdgeChange,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import EventCard from './EventCard';
import RelationDialog from './RelationDialog';
import { useUndoRedo } from '../hooks/useUndoRedo';
import { api } from '../api/client';
import type { Article } from '../types';

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
  const [nodes, setNodes, onNodesChangeRaw] = useNodesState<Node>(initialNodes);
  const [edges, setEdges, onEdgesChangeRaw] = useEdgesState<Edge>(initialEdges);
  const [relationDialog, setRelationDialog] = useState<{ from: string; to: string } | null>(null);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const isProcessingHistory = useRef(false);

  const applyHistory = useCallback((ns: Node[], es: Edge[]) => {
    isProcessingHistory.current = true;
    setNodes(ns);
    setEdges(es);
    // Reset flag after React commits
    setTimeout(() => { isProcessingHistory.current = false; }, 0);
  }, [setNodes, setEdges]);

  const { pushSnapshot, undo, redo, canUndo, canRedo } = useUndoRedo(applyHistory);

  // ── Push snapshot helper — debounces drag moves ─────────
  const snapshotTimer = useRef<ReturnType<typeof setTimeout>>();
  const scheduleSnapshot = useCallback(() => {
    if (isProcessingHistory.current) return;
    clearTimeout(snapshotTimer.current);
    snapshotTimer.current = setTimeout(() => {
      pushSnapshot(nodes, edges);
    }, 100);
  }, [nodes, edges, pushSnapshot]);

  // ── Wrap change handlers to detect deletes ──────────────
  const hadDelete = useRef(false);
  const onNodesChange: OnNodesChange = useCallback((changes: NodeChange[]) => {
    if (changes.some(c => c.type === 'remove')) hadDelete.current = true;
    onNodesChangeRaw(changes);
  }, [onNodesChangeRaw]);

  const onEdgesChange: OnEdgesChange = useCallback((changes: EdgeChange[]) => {
    if (changes.some(c => c.type === 'remove')) hadDelete.current = true;
    onEdgesChangeRaw(changes);
  }, [onEdgesChangeRaw]);

  // Capture snapshot after deletes settle
  useEffect(() => {
    if (hadDelete.current) {
      hadDelete.current = false;
      scheduleSnapshot();
    }
  });

  // ── Drop handler ────────────────────────────────────────
  const onDrop = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    const json = event.dataTransfer.getData('application/json');
    if (!json) return;
    const data = JSON.parse(json);
    if (data.type !== 'article') return;

    const article: Article = data.article;
    const eventName = article.event?.title || '未分类';

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
      scheduleSnapshot();
      return;
    }

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
    scheduleSnapshot();
  }, [nodes, setNodes, scheduleSnapshot]);

  const onDragOver = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  // ── Connection handler ──────────────────────────────────
  const onConnect = useCallback((connection: Connection) => {
    if (connection.source && connection.target) {
      setRelationDialog({ from: connection.source.toString(), to: connection.target.toString() });
    }
  }, []);

  const handleRelationSelect = useCallback(async (relation: string) => {
    if (!relationDialog) return;
    setEdges(eds => {
      const newEdges = addEdge({
        id: `e-${relationDialog.from}-${relationDialog.to}-${Date.now()}`,
        source: relationDialog.from,
        target: relationDialog.to,
        label: relation,
        style: { stroke: '#4fc3f7', strokeWidth: 2 },
        labelStyle: { fill: '#4fc3f7', fontSize: 10 },
        animated: true,
      }, eds);
      // Schedule snapshot with new edges
      setTimeout(() => pushSnapshot(nodes, newEdges), 50);
      return newEdges;
    });
    setRelationDialog(null);
  }, [relationDialog, setEdges, nodes, pushSnapshot]);

  // ── Keyboard shortcuts (Undo/Redo) ──────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
        if (e.shiftKey) {
          e.preventDefault();
          redo(nodes, edges);
        } else {
          e.preventDefault();
          undo(nodes, edges);
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [nodes, edges, undo, redo]);

  // ── Auto-save draft to localStorage (debounced 2s) ──────
  const saveTimer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => {
    if (chainId) return;
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({ nodes, edges }));
    }, 2000);
    return () => clearTimeout(saveTimer.current);
  }, [nodes, edges, chainId]);

  // ── Create chain handler ────────────────────────────────
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
        onNodeDragStop={scheduleSnapshot}
        onConnect={onConnect}
        onDrop={onDrop}
        onDragOver={onDragOver}
        nodeTypes={nodeTypes}
        fitView
        deleteKeyCode={['Backspace', 'Delete']}
        style={{ background: 'var(--bg-primary)' }}
      >
        <Controls />
        <Background color="#2a2a3e" gap={20} />
      </ReactFlow>

      {/* Toolbar */}
      <div style={{ position: 'absolute', top: 12, right: 12, display: 'flex', gap: 6, zIndex: 10 }}>
        <button
          onClick={() => undo(nodes, edges)}
          disabled={!canUndo}
          title="撤销 (Ctrl+Z)"
          style={{ ...toolbarBtn, opacity: canUndo ? 1 : 0.4 }}>
          ↩
        </button>
        <button
          onClick={() => redo(nodes, edges)}
          disabled={!canRedo}
          title="重做 (Ctrl+Shift+Z)"
          style={{ ...toolbarBtn, opacity: canRedo ? 1 : 0.4 }}>
          ↪
        </button>
        {nodes.length > 0 && (
          <button onClick={handleCreateChain} style={{
            background: 'var(--accent)', border: 'none', borderRadius: 6,
            padding: '6px 14px', color: '#000', fontWeight: 'bold', fontSize: 12, cursor: 'pointer',
          }}>
            ➕ 创建逻辑链
          </button>
        )}
      </div>

      <RelationDialog open={!!relationDialog} onClose={() => setRelationDialog(null)} onSelect={handleRelationSelect} />
    </div>
  );
}

const toolbarBtn: React.CSSProperties = {
  background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6,
  padding: '6px 10px', color: 'var(--text-primary)', fontSize: 16, cursor: 'pointer',
  width: 36, height: 36, display: 'flex', alignItems: 'center', justifyContent: 'center',
};
