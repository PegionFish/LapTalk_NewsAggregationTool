import { useState, useEffect, useCallback, useMemo } from 'react';
import { api } from '../api/client';
import type { Article } from '../types';
import ArticleBlock from './ArticleBlock';

interface Props {
  onSearchResults: (articles: Article[]) => void;
  onArticleSelect?: (article: Article) => void;
}

export default function SearchPanel({ onSearchResults, onArticleSelect }: Props) {
  const [query, setQuery] = useState('');
  const [datePreset, setDatePreset] = useState('today');
  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  const dateFrom = useMemo(() => {
    if (datePreset === 'today') return new Date().toISOString().slice(0, 10);
    if (datePreset === '3days') { const d = new Date(); d.setDate(d.getDate() - 3); return d.toISOString().slice(0, 10); }
    if (datePreset === '7days') { const d = new Date(); d.setDate(d.getDate() - 7); return d.toISOString().slice(0, 10); }
    return '';
  }, [datePreset]);

  const search = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { limit: 30, date_from: dateFrom };
      if (query) params.q = query;
      const res = await api.searchArticles(params);
      setArticles(res.articles || []);
      onSearchResults(res.articles || []);
    } catch { setArticles([]); }
    setLoading(false);
  }, [query, dateFrom, onSearchResults]);

  useEffect(() => { search(); }, [search]);

  if (collapsed) {
    return (
      <div onClick={() => setCollapsed(false)}
        style={{ width: 36, minWidth: 36, background: 'var(--bg-secondary)', borderRight: '1px solid var(--border)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer',
          color: 'var(--text-muted)', fontSize: 14, transition: 'var(--transition-fast)' }}
        title="展开搜索面板">
        <i className="fas fa-chevron-right" />
      </div>
    );
  }

  return (
    <div style={{ width: 280, minWidth: 280, background: 'var(--bg-secondary)', borderRight: '1px solid var(--border)',
      display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* 标题栏 */}
      <div style={{ padding: 10, borderBottom: '1px solid var(--border)', display: 'flex',
        justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 12, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6 }}>
          <i className="fas fa-search" style={{ color: 'var(--accent)', fontSize: 11 }} /> 文章检索
        </span>
        <button onClick={() => setCollapsed(true)}
          style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 12, padding: 2 }}
          title="收起面板">
          <i className="fas fa-chevron-left" />
        </button>
      </div>

      {/* 搜索条件 */}
      <div style={{ padding: 8, borderBottom: '1px solid var(--border)' }}>
        <input
          placeholder="搜索标题或关键词..."
          value={query}
          onChange={e => setQuery(e.target.value)}
          style={{
            width: '100%', background: 'var(--bg-primary)', border: '1px solid var(--border)',
            borderRadius: 5, padding: '6px 8px', color: 'var(--text-primary)', fontSize: 12, outline: 'none',
          }}
        />
        <div style={{ display: 'flex', gap: 4, marginTop: 6 }}>
          {[
            { key: 'today', label: '今天' },
            { key: '3days', label: '3天' },
            { key: '7days', label: '7天' },
          ].map(p => (
            <button key={p.key} onClick={() => setDatePreset(p.key)}
              style={{
                flex: 1, padding: '3px 0', borderRadius: 4, border: 'none', fontSize: 11, cursor: 'pointer',
                background: datePreset === p.key ? 'var(--accent)' : 'var(--bg-card)',
                color: datePreset === p.key ? '#000' : 'var(--text-secondary)',
                fontWeight: datePreset === p.key ? 600 : 400,
              }}>
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* 结果列表 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 6 }}>
        {loading && <div style={{ color: 'var(--text-muted)', fontSize: 12, textAlign: 'center', padding: 24 }}><i className="fas fa-spinner fa-spin" /> 搜索中...</div>}
        {!loading && articles.length === 0 && <div style={{ color: 'var(--text-muted)', fontSize: 12, textAlign: 'center', padding: 24 }}>无匹配文章</div>}
        {!loading && articles.map(a => <ArticleBlock key={a.id} article={a} onSelect={onArticleSelect} />)}
      </div>

      {/* 底栏计数 */}
      <div style={{ padding: '5px 10px', borderTop: '1px solid var(--border)', fontSize: 10, color: 'var(--text-muted)' }}>
        {articles.length} 条结果
      </div>
    </div>
  );
}
