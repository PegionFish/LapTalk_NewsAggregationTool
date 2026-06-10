import { useState, useEffect, useCallback } from 'react';
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
  const [open, setOpen] = useState(false);

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

  useEffect(() => { if (open) search(); }, [search, open]);

  const handleArticleClick = (article: Article) => {
    if (onArticleSelect) { onArticleSelect(article); setOpen(false); }
  };

  return (
    <>
      {/* 触发按钮 — 浮动在左上角 */}
      {!open && (
        <button onClick={() => setOpen(true)} style={triggerBtnStyle} title="搜索文章 (Ctrl+K)">
          <i className="fas fa-search" /> 搜索
        </button>
      )}

      {/* 浮动画板 — 从左侧滑入 */}
      {open && (
        <>
          <div onClick={() => setOpen(false)} style={backdropStyle} />
          <div style={panelStyle}>
            {/* 搜索栏 */}
            <div style={{ padding: 12, borderBottom: '1px solid var(--border)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <i className="fas fa-search" style={{ color: 'var(--accent)', fontSize: 13 }} />
                <input
                  placeholder="搜索新闻标题或关键词..."
                  value={query}
                  onChange={e => setQuery(e.target.value)}
                  autoFocus
                  style={{
                    flex: 1, background: 'var(--bg-primary)', border: '1px solid var(--border)',
                    borderRadius: 6, padding: '7px 10px', color: 'var(--text-primary)', fontSize: 13,
                    outline: 'none',
                  }}
                />
                <button onClick={() => setOpen(false)} style={closeBtnStyle}>
                  <i className="fas fa-times" />
                </button>
              </div>
              <div style={{ display: 'flex', gap: 4 }}>
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
                    }}>
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            {/* 结果列表 */}
            <div style={{ flex: 1, overflowY: 'auto', padding: 8 }}>
              {loading && <div style={statusStyle}><i className="fas fa-spinner fa-spin" /> 搜索中...</div>}
              {!loading && articles.length === 0 && <div style={statusStyle}>无结果</div>}
              {!loading && articles.map(a => <ArticleBlock key={a.id} article={a} onSelect={handleArticleClick} />)}
            </div>

            {/* 底栏提示 */}
            <div style={{ padding: '6px 12px', borderTop: '1px solid var(--border)', fontSize: 10, color: 'var(--text-muted)' }}>
              {articles.length} 条结果 · Esc 关闭
            </div>
          </div>
        </>
      )}
    </>
  );
}

// ── Styles ──

const triggerBtnStyle: React.CSSProperties = {
  position: 'absolute', top: 12, left: 12, zIndex: 10,
  display: 'flex', alignItems: 'center', gap: 6,
  background: 'var(--bg-secondary)', border: '1px solid var(--border)',
  borderRadius: 8, padding: '8px 14px', color: 'var(--text-secondary)',
  fontSize: 13, cursor: 'pointer', transition: 'var(--transition-fast)',
  boxShadow: 'var(--shadow-sm)',
};

const backdropStyle: React.CSSProperties = {
  position: 'absolute', inset: 0, zIndex: 40, background: 'rgba(0,0,0,0.3)',
};

const panelStyle: React.CSSProperties = {
  position: 'absolute', top: 0, left: 0, bottom: 0, width: 300, zIndex: 41,
  background: 'var(--bg-secondary)', borderRight: '1px solid var(--border)',
  display: 'flex', flexDirection: 'column',
  boxShadow: '8px 0 24px rgba(0,0,0,0.4)',
  animation: 'slideInRight 0.2s ease-out',
};

const closeBtnStyle: React.CSSProperties = {
  background: 'none', border: 'none', color: 'var(--text-muted)',
  cursor: 'pointer', fontSize: 14, padding: 4,
};

const statusStyle: React.CSSProperties = {
  color: 'var(--text-muted)', fontSize: 12, textAlign: 'center', padding: 20,
};
