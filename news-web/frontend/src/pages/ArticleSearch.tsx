import { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import type { Article } from '../types';

// ── useDebounce hook ─────────────────────────────────────
function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

const INPUT_STYLE: React.CSSProperties = {
  background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6,
  padding: '8px 12px', color: 'var(--text-primary)', fontSize: 13, outline: 'none',
};

export default function ArticleSearch() {
  const [articles, setArticles] = useState<Article[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState({ q: '', source: '', date_from: '', date_to: '', priority: '', verified: '' });
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Article | null>(null);

  const debouncedQuery = useDebounce(query, 300);  // 300ms debounce on filter changes

  const search = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const res = await api.searchArticles({ ...debouncedQuery, page: p, limit: 50 });
      setArticles(res.articles || []);
      setTotal(res.total);
      setPage(p);
    } catch { setArticles([]); }
    setLoading(false);
  }, [debouncedQuery]);

  useEffect(() => { search(1) }, [search]);

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>📄 文章检索</h2>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
        <input placeholder="关键词" value={query.q} onChange={e => setQuery(q => ({ ...q, q: e.target.value }))} style={{ ...INPUT_STYLE, flex: 1, minWidth: 200 }} />
        <input placeholder="来源" value={query.source} onChange={e => setQuery(q => ({ ...q, source: e.target.value }))} style={{ ...INPUT_STYLE, width: 120 }} />
        <input type="date" value={query.date_from} onChange={e => setQuery(q => ({ ...q, date_from: e.target.value }))} style={INPUT_STYLE} />
        <input type="date" value={query.date_to} onChange={e => setQuery(q => ({ ...q, date_to: e.target.value }))} style={INPUT_STYLE} />
        <select value={query.priority} onChange={e => setQuery(q => ({ ...q, priority: e.target.value }))} style={INPUT_STYLE}>
          <option value="">全部优先级</option>
          <option value="high">高</option><option value="medium">中</option><option value="low">低</option>
        </select>
        <select value={query.verified} onChange={e => setQuery(q => ({ ...q, verified: e.target.value }))} style={INPUT_STYLE}>
          <option value="">全部状态</option>
          <option value="no">待审核</option><option value="yes">已审核</option>
        </select>
        <button onClick={() => search(1)} style={{ background: 'var(--accent)', border: 'none', borderRadius: 6, padding: '8px 16px', color: '#000', fontWeight: 'bold', cursor: 'pointer' }}>搜索</button>
      </div>

      {/* Table */}
      <div style={{ background: 'var(--bg-secondary)', borderRadius: 10, overflow: 'hidden' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 100px 80px 70px 70px', gap: 8, padding: '10px 16px', fontSize: 12, color: 'var(--text-secondary)', borderBottom: '1px solid var(--border)', fontWeight: 'bold' }}>
          <span>标题</span><span>来源</span><span>评分</span><span>状态</span><span>日期</span>
        </div>
        {articles.map(a => (
          <div key={a.id}
            onClick={() => setSelected(a)}
            style={{ display: 'grid', gridTemplateColumns: '1fr 100px 80px 70px 70px', gap: 8, padding: '10px 16px', fontSize: 13, cursor: 'pointer', borderBottom: '1px solid var(--border)', background: selected?.id === a.id ? 'rgba(79,195,247,0.1)' : 'transparent' }}>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.title}</span>
            <span style={{ color: 'var(--accent)' }}>{a.source}</span>
            <span style={{ color: a.score > 0.7 ? 'var(--accent-green)' : a.score > 0.4 ? 'var(--accent-orange)' : 'var(--text-secondary)' }}>{a.score.toFixed(2)}</span>
            <span style={{ color: a.verified ? 'var(--accent-green)' : 'var(--accent-orange)' }}>{a.verified ? '已审' : '待审'}</span>
            <span style={{ color: 'var(--text-secondary)', fontSize: 12 }}>{a.fetched?.slice(5, 10)}</span>
          </div>
        ))}
        {!articles.length && <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-secondary)' }}>{loading ? '搜索中...' : '无结果'}</div>}
      </div>

      {total > 50 && (
        <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginTop: 16 }}>
          <button disabled={page <= 1} onClick={() => search(page - 1)} style={paginationBtn}>上一页</button>
          <span style={{ padding: '6px 12px', fontSize: 13, color: 'var(--text-secondary)' }}>{page} / {Math.ceil(total / 50)}</span>
          <button disabled={page >= Math.ceil(total / 50)} onClick={() => search(page + 1)} style={paginationBtn}>下一页</button>
        </div>
      )}

      {/* Detail Panel */}
      {selected && (
        <div style={{ marginTop: 16, background: 'var(--bg-secondary)', borderRadius: 10, padding: 20 }}>
          <h3 style={{ fontSize: 15, marginBottom: 8 }}>{selected.title}</h3>
          <div style={{ display: 'flex', gap: 16, fontSize: 13, color: 'var(--text-secondary)', marginBottom: 8 }}>
            <span>来源: {selected.source}</span>
            <span>评分: {selected.score.toFixed(2)}</span>
            <span>状态: {selected.verified ? '已审核' : '待审核'}</span>
          </div>
          {selected.keywords?.length > 0 && (
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 8 }}>
              {selected.keywords.map(k => <span key={k} style={{ background: 'var(--bg-card)', padding: '2px 8px', borderRadius: 4, fontSize: 11 }}>{k}</span>)}
            </div>
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            <a href={`/articles/${selected.id}`} style={{ background: 'var(--accent)', padding: '6px 14px', borderRadius: 6, fontSize: 12, color: '#000', textDecoration: 'none' }}>阅读全文</a>
            <a href={selected.url} target="_blank" rel="noopener noreferrer" style={{ background: 'var(--bg-card)', padding: '6px 14px', borderRadius: 6, fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>打开原文</a>
            {selected.event && (
              <a href={`/workspace?event=${selected.event.id}`} style={{ background: 'var(--bg-card)', padding: '6px 14px', borderRadius: 6, fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>查看所属事件 →</a>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

const paginationBtn: React.CSSProperties = {
  background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6,
  padding: '6px 14px', color: 'var(--text-primary)', fontSize: 13, cursor: 'pointer',
};
