import { useEffect, useState, useRef } from 'react';
import type { Article } from '../types';

interface Props {
  article: Article | null;
  onClose: () => void;
}

export default function ArticlePane({ article, onClose }: Props) {
  const [loaded, setLoaded] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    setLoaded(false);
  }, [article?.id]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    if (article) { window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler); }
  }, [article, onClose]);

  if (!article) return null;

  // 直连原站，广告/追踪脚本由浏览器自身沙箱处理
  return (
    <div style={overlayStyle}>
      <div onClick={onClose} style={{ position: 'absolute', inset: 0, zIndex: 0 }} />

      <div style={panelStyle}>
        <div style={headerStyle}>
          <span style={{ fontSize: 13, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
            {article.title.slice(0, 80)}
          </span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{article.source}</span>
          {article.url && (
            <a href={article.url} target="_blank" rel="noopener noreferrer"
              style={{ color: 'var(--accent)', fontSize: 13, padding: 4 }}
              title="在新标签页打开原文">
              <i className="fas fa-external-link-alt" />
            </a>
          )}
          <button onClick={onClose} style={closeBtn} title="关闭 (Esc)">
            <i className="fas fa-times" />
          </button>
        </div>

        <div style={{ flex: 1, position: 'relative', background: '#fff' }}>
          {!loaded && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-primary)', zIndex: 1 }}>
              <i className="fas fa-spinner fa-spin" style={{ color: 'var(--accent)', fontSize: 20, marginRight: 8 }} />
              <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>加载中...</span>
            </div>
          )}
          <iframe
            ref={iframeRef}
            src={`/api/articles/${article.id}/html`}
            onLoad={() => setLoaded(true)}
            style={{ width: '100%', height: '100%', border: 'none' }}
            sandbox="allow-popups"
            title={article.title}
          />
        </div>
      </div>
    </div>
  );
}

const overlayStyle: React.CSSProperties = {
  position: 'absolute', top: 0, right: 0, bottom: 0, width: '55%', minWidth: 480, maxWidth: 900,
  zIndex: 50,
};

const panelStyle: React.CSSProperties = {
  position: 'absolute', top: 0, right: 0, bottom: 0, width: '100%',
  background: 'var(--bg-secondary)', borderLeft: '1px solid var(--border)',
  display: 'flex', flexDirection: 'column',
  boxShadow: '-8px 0 24px rgba(0,0,0,0.5)',
  zIndex: 1, animation: 'slideInRight 0.2s ease-out',
};

const headerStyle: React.CSSProperties = {
  padding: '8px 14px', borderBottom: '1px solid var(--border)',
  display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0,
};

const closeBtn: React.CSSProperties = {
  background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer',
  fontSize: 14, padding: 4, borderRadius: 4,
};

