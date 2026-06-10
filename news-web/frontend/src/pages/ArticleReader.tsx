import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { Article, ArticleContent } from '../types';

export default function ArticleReader() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [article, setArticle] = useState<Article | null>(null);
  const [content, setContent] = useState<ArticleContent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [synced, setSynced] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    Promise.all([
      api.getArticle(Number(id)).catch(() => null),
      api.getArticleContent(Number(id)).catch(() => null),
    ]).then(([art, con]) => {
      setArticle(art as Article | null);
      setContent(con as ArticleContent | null);
      if (!art && !con) setError('文章不存在或内容不可用');
    }).catch(() => {
      setError('加载失败');
    }).finally(() => setLoading(false));
  }, [id]);

  // 同步左右栏滚动
  const handleScroll = (e: React.UIEvent<HTMLDivElement>, side: 'left' | 'right') => {
    if (synced) return;
    setSynced(true);
    const other = document.getElementById(side === 'left' ? 'col-right' : 'col-left');
    if (other) other.scrollTop = (e.target as HTMLDivElement).scrollTop;
    setTimeout(() => setSynced(false), 50);
  };

  const hasTranslation = content?.translation && content.translation.length > 0;

  if (loading) {
    return <div style={centerStyle}><span style={{ color: 'var(--text-secondary)' }}>加载中...</span></div>;
  }
  if (error) {
    return <div style={centerStyle}><span style={{ color: 'var(--accent-red)' }}>{error}</span></div>;
  }

  return (
    <div style={{ maxWidth: hasTranslation ? '100%' : 800, margin: '0 auto', padding: '0 16px' }}>
      {/* 顶栏元数据 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
        <button onClick={() => navigate(-1)} style={backBtnStyle}>← 返回</button>
        <div style={{ flex: 1 }}>
          <h1 style={{ fontSize: 20, margin: 0, lineHeight: 1.3 }}>
            {article?.title || '文章阅读'}
          </h1>
          <div style={{ display: 'flex', gap: 12, marginTop: 6, fontSize: 12, color: 'var(--text-secondary)' }}>
            {article?.source && <span>📰 {article.source}</span>}
            {article?.fetched && <span>📅 {article.fetched.slice(0, 10)}</span>}
            {content?.lang && <span>🌐 {content.lang === 'zh' ? '中文' : content.lang.toUpperCase()}</span>}
            {article?.score !== undefined && (
              <span style={{ color: article.score > 0.7 ? 'var(--accent-green)' : article.score > 0.4 ? 'var(--accent-orange)' : 'var(--text-secondary)' }}>
                ⭐ {article.score.toFixed(2)}
              </span>
            )}
            {content?.source === 'local' && <span style={{ color: 'var(--accent-green)' }}>💾 本地缓存</span>}
          </div>
          {article?.keywords && article.keywords.length > 0 && (
            <div style={{ display: 'flex', gap: 4, marginTop: 8, flexWrap: 'wrap' }}>
              {article.keywords.slice(0, 10).map(kw => (
                <span key={kw} style={tagStyle}>{kw}</span>
              ))}
            </div>
          )}
        </div>
        {article?.url && (
          <a href={article.url} target="_blank" rel="noopener noreferrer" style={extLinkStyle}>
            🔗 原文
          </a>
        )}
      </div>

      {/* 内容区 */}
      {hasTranslation ? (
        <div style={{ display: 'flex', gap: 16, height: 'calc(100vh - 180px)' }}>
          <div id="col-left" onScroll={e => handleScroll(e, 'left')}
            style={colStyle}>
            <div style={colHeaderStyle}>📄 原文 ({content!.lang.toUpperCase()})</div>
            <div style={proseStyle}>{content!.content}</div>
          </div>
          <div id="col-right" onScroll={e => handleScroll(e, 'right')}
            style={colStyle}>
            <div style={{ ...colHeaderStyle, color: 'var(--accent)' }}>🌐 译文 (中文)</div>
            <div style={proseStyle}>{content!.translation}</div>
          </div>
        </div>
      ) : (
        <div style={{ maxHeight: 'calc(100vh - 200px)', overflowY: 'auto', background: 'var(--bg-secondary)', borderRadius: 10, padding: 24 }}>
          {content?.content ? (
            <div style={proseStyle}>{content.content}</div>
          ) : (
            <div style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: 40 }}>
              内容暂不可用 — 该文章可能尚未完成内容抓取或翻译。
              <br />
              {article?.url && (
                <a href={article.url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)', marginTop: 8, display: 'inline-block' }}>
                  查看原文 →
                </a>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const centerStyle: React.CSSProperties = {
  display: 'flex', alignItems: 'center', justifyContent: 'center', height: '60vh',
};

const backBtnStyle: React.CSSProperties = {
  background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6,
  padding: '6px 14px', color: 'var(--text-primary)', cursor: 'pointer', fontSize: 13,
};

const extLinkStyle: React.CSSProperties = {
  color: 'var(--accent)', fontSize: 13, textDecoration: 'none',
  padding: '6px 14px', borderRadius: 6, border: '1px solid var(--border)',
};

const tagStyle: React.CSSProperties = {
  background: 'var(--bg-card)', padding: '2px 8px', borderRadius: 10, fontSize: 11,
  color: 'var(--text-secondary)', border: '1px solid var(--border)',
};

const colStyle: React.CSSProperties = {
  flex: 1, overflowY: 'auto', background: 'var(--bg-secondary)',
  borderRadius: 10, padding: 16,
};

const colHeaderStyle: React.CSSProperties = {
  fontSize: 12, fontWeight: 'bold', color: 'var(--text-secondary)',
  marginBottom: 12, borderBottom: '1px solid var(--border)', paddingBottom: 8,
};

const proseStyle: React.CSSProperties = {
  fontSize: 14, lineHeight: 1.8, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
  color: 'var(--text-primary)',
};
