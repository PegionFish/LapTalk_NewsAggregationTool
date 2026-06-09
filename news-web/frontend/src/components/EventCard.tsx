import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { Node } from '@xyflow/react';
import type { Article } from '../types';

interface EventNodeData {
  eventId: number;
  title: string;
  priority: string;
  articles: Article[];
}

type EventNode = Node & { data: EventNodeData };

function EventCard({ data }: { data: EventNodeData }) {
  const priorityColor = data.priority === 'high' ? 'var(--accent-green)' :
    data.priority === 'medium' ? 'var(--accent-orange)' : 'var(--accent-purple)';

  return (
    <div style={{
      background: 'var(--bg-secondary)', border: `1px solid ${priorityColor}`, borderRadius: 10,
      padding: 12, minWidth: 280, maxWidth: 360, fontSize: 12, boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
    }}>
      <Handle type="target" position={Position.Left} style={{ background: priorityColor, width: 8, height: 8 }} />
      <div style={{ fontWeight: 'bold', fontSize: 13, marginBottom: 2, color: priorityColor }}>📦 {data.title}</div>
      <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginBottom: 8 }}>
        {data.articles.length} 篇文章 · {data.priority === 'high' ? '高' : data.priority === 'medium' ? '中' : '低'}优先级
      </div>
      <div style={{ borderTop: '1px solid var(--border)', paddingTop: 6 }}>
        {data.articles.slice(0, 5).map((a: Article) => (
          <div key={a.id} style={{ padding: '3px 0', fontSize: 11, color: 'var(--text-primary)', display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>{a.title}</span>
            <span style={{ color: 'var(--accent)', fontSize: 10, marginLeft: 8 }}>{a.source}</span>
          </div>
        ))}
        {data.articles.length > 5 && <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 4 }}>+{data.articles.length - 5} 篇</div>}
      </div>
      <Handle type="source" position={Position.Right} style={{ background: priorityColor, width: 8, height: 8 }} />
    </div>
  );
}

export default memo(EventCard) as unknown as (props: unknown) => JSX.Element;
