import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { Article } from '../types';

export default function ArticleReader() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [article, setArticle] = useState<Article | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [iframeLoaded, setIframeLoaded] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setIframeLoaded(false);
    api.getArticle(Number(id))
      .then(a => setArticle(a as Article))
      .catch(() => setError('文章不存在'))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return <div style={center}><i className="fas fa-spinner fa-spin" style={{ color: 'var(--accent)', fontSize: 18 }} /><span style={{ color: 'var(--text-secondary)', marginLeft: 8 }}>加载中...</span></div>;
  }
  if (error) {
    return <div style={center}><span style={{ color: 'var(--accent-red)' }}>{error}</span></div>;
  }
  if (!article) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* 顶栏 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 16px', borderBottom: '1px solid var(--border)', flexShrink: 0, background: 'var(--bg-secondary)' }}>
        <button onClick={() => navigate(-1)} style={backBtn}>
          <i className="fas fa-arrow-left" />
        </button>
        <div style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>{article.title}</span>
          <span style={{ marginLeft: 12, fontSize: 11, color: 'var(--text-muted)' }}>{article.source}</span>
        </div>
        <a href={article.url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)', fontSize: 13, textDecoration: 'none' }}>
          <i className="fas fa-external-link-alt" /> 新窗口
        </a>
      </div>

      {/* iframe */}
      <div style={{ flex: 1, position: 'relative', background: '#fff' }}>
        {!iframeLoaded && (
          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-primary)', zIndex: 1 }}>
            <i className="fas fa-spinner fa-spin" style={{ color: 'var(--accent)', fontSize: 20, marginRight: 8 }} />
            <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>加载页面...</span>
          </div>
        )}
        <iframe
          src={`/api/articles/${id}/html`}
          onLoad={() => setIframeLoaded(true)}
          style={{ width: '100%', height: '100%', border: 'none' }}
          sandbox="allow-scripts allow-same-origin allow-popups"
          title={article.title}
        />
      </div>
    </div>
  );
}

const center: React.CSSProperties = {
  display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%',
};

const backBtn: React.CSSProperties = {
  background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6,
  padding: '6px 12px', color: 'var(--text-primary)', cursor: 'pointer', fontSize: 13,
};
