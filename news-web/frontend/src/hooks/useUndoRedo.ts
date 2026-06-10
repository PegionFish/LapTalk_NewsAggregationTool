import { useCallback, useRef, useState } from 'react';
import type { Node, Edge } from '@xyflow/react';

interface HistoryEntry {
  nodes: Node[];
  edges: Edge[];
}

const MAX_HISTORY = 50;

/**
 * Custom undo/redo hook for React Flow state.
 * Tracks node and edge snapshots with 50-step limit.
 * Returns [pushSnapshot, undo, redo, canUndo, canRedo].
 *
 * Usage: call pushSnapshot() after every state change,
 * then undo()/redo() to travel through history.
 */
export function useUndoRedo(
  onApply: (nodes: Node[], edges: Edge[]) => void,
) {
  const past = useRef<HistoryEntry[]>([]);
  const future = useRef<HistoryEntry[]>([]);
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);

  const pushSnapshot = useCallback((nodes: Node[], edges: Edge[]) => {
    past.current.push({ nodes: structuredClone(nodes), edges: structuredClone(edges) });
    if (past.current.length > MAX_HISTORY) {
      past.current.shift();
    }
    future.current = [];
    setCanUndo(past.current.length > 0);
    setCanRedo(false);
  }, []);

  const undo = useCallback((currentNodes: Node[], currentEdges: Edge[]) => {
    if (past.current.length === 0) return;
    future.current.push({ nodes: structuredClone(currentNodes), edges: structuredClone(currentEdges) });
    const prev = past.current.pop()!;
    onApply(prev.nodes, prev.edges);
    setCanUndo(past.current.length > 0);
    setCanRedo(true);
  }, [onApply]);

  const redo = useCallback((currentNodes: Node[], currentEdges: Edge[]) => {
    if (future.current.length === 0) return;
    past.current.push({ nodes: structuredClone(currentNodes), edges: structuredClone(currentEdges) });
    const next = future.current.pop()!;
    onApply(next.nodes, next.edges);
    setCanUndo(true);
    setCanRedo(future.current.length > 0);
  }, [onApply]);

  return { pushSnapshot, undo, redo, canUndo, canRedo };
}
