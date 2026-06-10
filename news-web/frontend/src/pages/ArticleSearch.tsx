import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { Article } from '../types';

const PER_PAGE = 50;

export default function ArticleSearch() {
  const navigate = useNavigate();
  const [articles, setArticles] = useState<Article[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [priority, setPriority] = useState('');
  const [verified, setVerified] = useState('');
  const [selected, setSelected] = useState<Article | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailHtml, setDetailHtml] = useState('');

  const fetchArticles = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { page, limit: PER_PAGE };
      if (search) params.q = search;
      if (priority) params.priority = priority;
      if (verified === 'yes') params.verified = 'yes';
      else if (verified === 'no') params.verified = 'no';
      const res = await api.searchArticles(params);
      setArticles(res.articles || []);
      setTotal(res.total || 0);
    } catch { setArticles([]); }
    setLoading(false);
  }, [page, search, priority, verified]);

  useEffect(() => { fetchArticles(); }, [fetchArticles]);

  // 选中文章时获取内容
  useEffect(() => {
    if (!selected) { setDetailHtml(''); return; }
    api.getArticleContent(selected.id).then(c => {
      if (c?.content) {
        const display = c.translation || c.content;
        setDetailHtml(display.substring(0, 5000));
      }
    }).catch(() => setDetailHtml(''));
  }, [selected?.id]);

  const totalPages = Math.ceil(total / PER_PAGE);

  return (
    <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
      {/* 中：文章列表 */}
      <div style={{ flex: 1, overflow: 'auto', padding: 24 }}>
        {/* 工具栏 */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          <input
            placeholder="搜索标题或关键词..."
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1); }}
            style={inputStyle}
          />
          <select value={priority} onChange={e => { setPriority(e.target.value); setPage(1); }} style={selectStyle}>
            <option value="">全部优先级</option>
            <option value="high">高</option>
            <option value="medium">中</option>
            <option value="low">低</option>
          </select>
          <select value={verified} onChange={e => { setVerified(e.target.value); setPage(1); }} style={selectStyle}>
            <option value="">全部状态</option>
            <option value="yes">已审核</option>
            <option value="no">待审核</option>
          </select>
          {loading && <i className="fas fa-spinner fa-spin" style={{ color: 'var(--accent)', fontSize: 13 }} />}
        </div>

        {/* 表格 */}
        <div style={{ background: 'var(--bg-secondary)', borderRadius: 10, border: '1px solid var(--border)', overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)', background: 'rgba(0,0,0,0.1)' }}>
                <th style={thStyle}>标题</th>
                <th style={{ ...thStyle, width: 100 }}>来源</th>
                <th style={{ ...thStyle, width: 70 }}>评分</th>
                <th style={{ ...thStyle, width: 60 }}>状态</th>
                <th style={{ ...thStyle, width: 70 }}>日期</th>
              </tr>
            </thead>
            <tbody>
              {articles.map(a => (
                <tr key={a.id}
                  onClick={() => setSelected(a)}
                  style={{
                    cursor: 'pointer', borderBottom: '1px solid var(--border)',
                    background: selected?.id === a.id ? 'rgba(0,212,255,0.06)' : 'transparent',
                    transition: 'var(--transition-fast)',
                  }}>
                  <td style={{ padding: '7px 12px', fontWeight: selected?.id === a.id ? 600 : 400, maxWidth: 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.title}</td>
                  <td style={{ padding: '7px 12px', color: 'var(--text-secondary)', fontSize: 11 }}>{a.source}</td>
                  <td style={{ padding: '7px 12px', color: a.score > 0.7 ? 'var(--accent-tertiary)' : a.score > 0.4 ? 'var(--accent-orange)' : 'var(--text-muted)', fontWeight: 600 }}>
                    {a.score.toFixed(2)}
                  </td>
                  <td style={{ padding: '7px 12px', fontSize: 11 }}><span style={{ color: a.verified ? 'var(--accent-tertiary)' : 'var(--text-muted)' }}>{a.verified ? '已审' : '待审'}</span></td>
                  <td style={{ padding: '7px 12px', color: 'var(--text-muted)', fontSize: 11 }}>{a.fetched?.slice(5, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* 分页 */}
        {totalPages > 1 && (
          <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginTop: 16 }}>
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1} style={pageBtnStyle}>
              <i className="fas fa-chevron-left" /> 上一页
            </button>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)', padding: '6px 12px' }}>
              {page} / {totalPages} · 共 {total} 条
            </span>
            <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages} style={pageBtnStyle}>
              下一页 <i className="fas fa-chevron-right" />
            </button>
          </div>
        )}
      </div>

      {/* 右：详情面板 */}
      {selected && (
        <div style={{ width: 380, minWidth: 380, background: 'var(--bg-secondary)', borderLeft: '1px solid var(--border)',
          overflow: 'auto', padding: 20, display: 'flex', flexDirection: 'column' }}>
          <button onClick={() => setSelected(null)}
            style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 13, alignSelf: 'flex-end', padding: 4 }}>
            <i className="fas fa-times" />
          </button>

          <h3 style={{ fontSize: 15, marginTop: 0, lineHeight: 1.4 }}>{selected.title}</h3>

          <div style={{ display: 'flex', gap: 12, marginTop: 12, flexWrap: 'wrap', fontSize: 12 }}>
            <span style={{ color: 'var(--text-secondary)' }}>📰 {selected.source}</span>
            <span style={{ color: 'var(--text-secondary)' }}>📅 {selected.fetched?.slice(0, 10)}</span>
            <span style={{ color: selected.score > 0.7 ? 'var(--accent-tertiary)' : 'var(--accent-orange)' }}>⭐ {selected.score.toFixed(2)}</span>
            <span style={{ color: selected.verified ? 'var(--accent-tertiary)' : 'var(--text-muted)' }}>{selected.verified ? '✓ 已审核' : '待审核'}</span>
          </div>

          {selected.keywords?.length > 0 && (
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 12 }}>
              {selected.keywords.map(k => (
                <span key={k} style={kwStyle}>{k}</span>
              ))}
            </div>
          )}

          <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
            <button onClick={() => navigate(`/articles/${selected.id}`)} style={actionBtnStyle}>
              <i className="fas fa-book-open" /> 阅读全文
            </button>
            <a href={selected.url} target="_blank" rel="noopener noreferrer" style={{ ...actionBtnStyle, background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-secondary)', textDecoration: 'none' }}>
              <i className="fas fa-external-link-alt" /> 原文
            </a>
          </div>

          {selected.event && (
            <a href={`/workspace?event=${selected.event.id}`} style={{
              marginTop: 10, display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12,
              color: 'var(--accent)', textDecoration: 'none',
            }}>
              <i className="fas fa-diagram-project" /> 查看所属事件: {selected.event.title}
            </a>
          )}

          <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '16px 0' }} />

          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>📄 内容预览</div>
          <div style={{ fontSize: 12, lineHeight: 1.8, color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', flex: 1, overflow: 'auto' }}>
            {detailHtml || '内容暂不可用。该文章可能尚未完成内容抓取。'}
          </div>
        </div>
      )}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6,
  padding: '7px 12px', color: 'var(--text-primary)', fontSize: 13, outline: 'none',
  flex: 1, minWidth: 200,
};
const selectStyle: React.CSSProperties = {
  background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6,
  padding: '6px 10px', color: 'var(--text-primary)', fontSize: 12, outline: 'none', cursor: 'pointer',
};
const thStyle: React.CSSProperties = {
  textAlign: 'left', padding: '9px 12px', fontWeight: 600, fontSize: 11, color: 'var(--text-muted)',
  textTransform: 'uppercase', letterSpacing: 0.5,
};
const pageBtnStyle: React.CSSProperties = {
  background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6,
  padding: '6px 14px', color: 'var(--text-primary)', fontSize: 12, cursor: 'pointer',
  display: 'flex', alignItems: 'center', gap: 6,
};
const kwStyle: React.CSSProperties = {
  background: 'rgba(0,212,255,0.08)', padding: '2px 8px', borderRadius: 10, fontSize: 10,
  color: 'var(--text-secondary)', border: '1px solid var(--border)',
};
const actionBtnStyle: React.CSSProperties = {
  background: 'var(--accent)', border: 'none', borderRadius: 6, padding: '7px 16px',
  color: '#000', fontWeight: 600, fontSize: 12, cursor: 'pointer',
  display: 'flex', alignItems: 'center', gap: 6,
};
