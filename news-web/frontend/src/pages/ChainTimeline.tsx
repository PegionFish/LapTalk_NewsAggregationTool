import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { Button, Loading } from '../components/ui';
import type { ChainEvent } from '../types';

interface TimelineData { chain_id: number; chain_title: string; timeline: ChainEvent[]; total_events: number; }

export default function ChainTimelinePage() {
  const { chainId } = useParams<{ chainId: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<TimelineData | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedEvents, setExpandedEvents] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (!chainId) return;
    api.getChainTimeline(Number(chainId))
      .then(d => setData(d))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [chainId]);

  const toggleEvent = (id: number) => {
    setExpandedEvents(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (loading) return <Loading text="加载逻辑链..." />;
  if (!data) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
        <p>逻辑链未找到</p>
        <Button variant="ghost" onClick={() => navigate('/chains')}>返回列表</Button>
      </div>
    );
  }

  return (
    <div style={{ padding: 24, overflow: 'auto', flex: 1, maxWidth: 900, margin: '0 auto' }}>
      {/* 返回 + 标题 */}
      <Button variant="ghost" icon="fa-arrow-left" onClick={() => navigate('/chains')}
        style={{ marginBottom: 16 }}>
        返回列表
      </Button>
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontSize: 22, fontWeight: 700, margin: '0 0 8px', display: 'flex', alignItems: 'center', gap: 10 }}>
          <i className="fas fa-timeline" style={{ color: 'var(--accent)' }} />
          {data.chain_title}
        </h2>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', display: 'flex', gap: 16 }}>
          <span><i className="fas fa-diagram-project" style={{ marginRight: 4 }} />{data.total_events} 个事件</span>
          <span><i className="fas fa-robot" style={{ marginRight: 4, color: 'var(--accent)' }} />AI 生成</span>
        </div>
      </div>

      {/* 时间线 */}
      <div style={{ position: 'relative', paddingLeft: 32 }}>
        {/* 竖线 */}
        <div style={{
          position: 'absolute', left: 11, top: 8, bottom: 8,
          width: 2, background: 'var(--border-color)',
        }} />

        {data.timeline.map((evt, idx) => {
          const isExpanded = expandedEvents.has(evt.id);
          const articles = evt.articles || [];
          const hasArticles = articles.length > 0;
          const priorityColor = evt.article_count >= 20 ? 'var(--accent)' :
                                evt.article_count >= 10 ? '#ffb74d' : 'var(--text-muted)';

          return (
            <div key={evt.id} style={{ marginBottom: idx < data.timeline.length - 1 ? 20 : 0 }}>
              {/* 时间点 */}
              <div style={{
                position: 'absolute', left: 0,
                width: 24, height: 24, borderRadius: '50%',
                background: priorityColor,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: '#fff', fontSize: 10, fontWeight: 700,
                transform: 'translateX(-11px)',
                zIndex: 1,
              }}>
                {idx + 1}
              </div>

              {/* 事件卡片 */}
              <div
                onClick={() => hasArticles && toggleEvent(evt.id)}
                style={{
                  background: 'var(--bg-secondary)',
                  border: '1px solid var(--border-color)',
                  borderRadius: 8,
                  padding: '12px 16px',
                  cursor: hasArticles ? 'pointer' : 'default',
                  transition: 'border-color 0.15s',
                }}
                onMouseEnter={e => { if (hasArticles) (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--border-color)'; }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text-primary)', marginBottom: 4 }}>
                      {evt.title}
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                      <span>{evt.first_seen} ~ {evt.last_seen}</span>
                      <span style={{ color: priorityColor, fontWeight: 600 }}>
                        <i className="fas fa-newspaper" style={{ marginRight: 3 }} />{evt.article_count} 篇
                      </span>
                      {evt.note && (
                        <span style={{ color: 'var(--accent)', fontStyle: 'italic' }}>
                          {evt.note.replace('AI: ', '')}
                        </span>
                      )}
                    </div>
                  </div>
                  {hasArticles && (
                    <i className={`fas fa-chevron-${isExpanded ? 'up' : 'down'}`}
                      style={{ color: 'var(--text-muted)', fontSize: 12, marginLeft: 12, marginTop: 4 }} />
                  )}
                </div>

                {/* 展开的文章列表 */}
                {isExpanded && hasArticles && (
                  <div style={{ marginTop: 12, borderTop: '1px solid var(--border-color)', paddingTop: 10 }}>
                    {articles.map(a => (
                      <a
                        key={a.id}
                        href={a.url || `#`}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                          display: 'flex', alignItems: 'center', gap: 8,
                          padding: '6px 8px', borderRadius: 4,
                          textDecoration: 'none', color: 'var(--text-primary)',
                          fontSize: 13,
                          transition: 'background 0.1s',
                        }}
                        onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = 'var(--bg-hover)'}
                        onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'transparent'}
                      >
                        <span style={{
                          fontSize: 10, fontWeight: 600, color: '#fff',
                          background: evt.article_count >= 20 ? 'var(--accent)' :
                                      evt.article_count >= 10 ? '#ffb74d' : 'var(--text-muted)',
                          borderRadius: 3, padding: '1px 5px', flexShrink: 0,
                          minWidth: 24, textAlign: 'center',
                        }}>
                          {a.priority_score > 70 ? '高' : a.priority_score > 40 ? '中' : '低'}
                        </span>
                        <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {a.title}
                        </span>
                        <span style={{ color: 'var(--text-muted)', fontSize: 11, flexShrink: 0 }}>
                          [{a.source}]
                        </span>
                        <i className="fas fa-external-link-alt" style={{ color: 'var(--text-muted)', fontSize: 10, flexShrink: 0 }} />
                      </a>
                    ))}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
