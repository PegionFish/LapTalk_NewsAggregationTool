import { useState, useEffect, useCallback } from 'react';
import { api } from '../api/client';
import type { Article } from '../types';
import ArticleBlock from './ArticleBlock';

interface Props {
  onSearchResults: (articles: Article[]) => void;
}

export default function SearchPanel({ onSearchResults }: Props) {
  const [query, setQuery] = useState('');
  const [datePreset, setDatePreset] = useState('today');
  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  const search = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { limit: 30 };
      if (query) params.q = query;
      if (datePreset === 'today') params.date_from = new Date().toISOString().slice(0, 10);
      else if (datePreset === '3days') {
        const d = new Date(); d.setDate(d.getDate() - 3);
        params.date_from = d.toISOString().slice(0, 10);
      } else if (datePreset === '7days') {
        const d = new Date(); d.setDate(d.getDate() - 7);
        params.date_from = d.toISOString().slice(0, 10);
      }
      const res = await api.searchArticles(params);
      setArticles(res.articles || []);
      onSearchResults(res.articles || []);
    } catch { setArticles([]); }
    setLoading(false);
  }, [query, datePreset, onSearchResults]);

  useEffect(() => { search() }, [search]);

  if (collapsed) {
    return (
      <div style={{ width: 40, background: 'var(--bg-secondary)', borderRight: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}
        onClick={() => setCollapsed(false)}>
        <span style={{ fontSize: 20, transform: 'rotate(180deg)' }}>▶</span>
      </div>
    );
  }

  return (
    <div style={{ width: 280, background: 'var(--bg-secondary)', borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ padding: 12, borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 13, fontWeight: 'bold' }}>🔍 搜索</span>
        <span style={{ cursor: 'pointer', fontSize: 12, color: 'var(--text-secondary)' }} onClick={() => setCollapsed(true)}>◀ 收起</span>
      </div>

      <div style={{ padding: '8px 12px' }}>
        <input placeholder="搜索新闻..." value={query} onChange={e => setQuery(e.target.value)}
          style={{ width: '100%', background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 10px', color: 'var(--text-primary)', fontSize: 12, outline: 'none' }} />
        <div style={{ display: 'flex', gap: 4, marginTop: 6 }}>
          {['today', '3days', '7days'].map(p => (
            <button key={p} onClick={() => setDatePreset(p)}
              style={{ flex: 1, padding: '4px 0', borderRadius: 4, border: 'none', fontSize: 11, cursor: 'pointer',
                background: datePreset === p ? 'var(--accent)' : 'var(--bg-card)', color: datePreset === p ? '#000' : 'var(--text-secondary)' }}>
              {p === 'today' ? '今天' : p === '3days' ? '3天' : '7天'}
            </button>
          ))}
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '4px 12px' }}>
        {loading && <div style={{ color: 'var(--text-secondary)', fontSize: 12, textAlign: 'center', padding: 20 }}>搜索中...</div>}
        {!loading && articles.length === 0 && <div style={{ color: 'var(--text-secondary)', fontSize: 12, textAlign: 'center', padding: 20 }}>无结果</div>}
        {!loading && articles.map(a => <ArticleBlock key={a.id} article={a} />)}
      </div>
    </div>
  );
}
