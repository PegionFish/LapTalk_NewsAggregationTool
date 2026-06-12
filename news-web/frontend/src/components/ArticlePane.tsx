import { useEffect, useState, useRef, useCallback } from 'react';
import { api } from '../api/client';
import type { Article } from '../types';

interface Props {
  article: Article | null;
  onClose: () => void;
}

interface ArticleContent {
  translation: string;
  lang: string;
}

export default function ArticlePane({ article, onClose }: Props) {
  const [loaded, setLoaded] = useState(false);
  const [showTranslation, setShowTranslation] = useState(false);
  const [content, setContent] = useState<ArticleContent | null>(null);
  const [contentLoading, setContentLoading] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const translationRef = useRef<HTMLDivElement>(null);
  const syncingRef = useRef(false);

  useEffect(() => {
    setLoaded(false);
    setShowTranslation(false);
    setContent(null);
  }, [article?.id]);

  useEffect(() => {
    if (!article) return;
    setContentLoading(true);
    api.getArticleContent(article.id)
      .then(c => setContent({ translation: c.translation, lang: c.lang }))
      .catch(() => setContent(null))
      .finally(() => setContentLoading(false));
  }, [article?.id]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    if (article) { window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler); }
  }, [article, onClose]);

  const handleIframeScroll = useCallback(() => {
    if (syncingRef.current || !showTranslation) return;
    const iframe = iframeRef.current;
    const panel = translationRef.current;
    if (!iframe?.contentDocument?.documentElement || !panel) return;
    syncingRef.current = true;
    const iframeDoc = iframe.contentDocument.documentElement;
    const ratio = iframeDoc.scrollTop / (iframeDoc.scrollHeight - iframeDoc.clientHeight || 1);
    panel.scrollTop = ratio * (panel.scrollHeight - panel.clientHeight);
    requestAnimationFrame(() => { syncingRef.current = false; });
  }, [showTranslation]);

  const handleTranslationScroll = useCallback(() => {
    if (syncingRef.current) return;
    const iframe = iframeRef.current;
    const panel = translationRef.current;
    if (!iframe?.contentDocument?.documentElement || !panel) return;
    syncingRef.current = true;
    const iframeDoc = iframe.contentDocument.documentElement;
    const ratio = panel.scrollTop / (panel.scrollHeight - panel.clientHeight || 1);
    iframeDoc.scrollTop = ratio * (iframeDoc.scrollHeight - iframeDoc.clientHeight);
    requestAnimationFrame(() => { syncingRef.current = false; });
  }, []);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    const onLoad = () => {
      setLoaded(true);
      try {
        iframe.contentDocument?.addEventListener('scroll', handleIframeScroll);
      } catch {}
    };
    iframe.addEventListener('load', onLoad);
    return () => {
      iframe.removeEventListener('load', onLoad);
      try {
        iframe.contentDocument?.removeEventListener('scroll', handleIframeScroll);
      } catch {}
    };
  }, [handleIframeScroll]);

  if (!article) return null;

  const hasTranslation = content?.translation && content.translation.length > 0;
  const isEnglish = content?.lang === 'en';

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
          {isEnglish && hasTranslation && (
            <button
              onClick={() => setShowTranslation(v => !v)}
              style={{
                ...toggleBtn,
                background: showTranslation ? 'var(--accent-tertiary)' : 'var(--bg-card)',
                color: showTranslation ? '#000' : 'var(--text-secondary)',
              }}
              title={showTranslation ? '隐藏译文' : '显示译文'}
            >
              <i className={`fas ${showTranslation ? 'fa-columns' : 'fa-language'}`} />
              <span>{showTranslation ? '对照' : '译文'}</span>
            </button>
          )}
          <button onClick={onClose} style={closeBtn} title="关闭 (Esc)">
            <i className="fas fa-times" />
          </button>
        </div>

        <div style={{ flex: 1, display: 'flex', position: 'relative', overflow: 'hidden' }}>
          {!loaded && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-primary)', zIndex: 1 }}>
              <i className="fas fa-spinner fa-spin" style={{ color: 'var(--accent)', fontSize: 20, marginRight: 8 }} />
              <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>加载中...</span>
            </div>
          )}

          <div style={{ flex: 1, position: 'relative', background: '#fff' }}>
            <iframe
              ref={iframeRef}
              src={`/api/articles/${article.id}/html`}
              onLoad={() => setLoaded(true)}
              style={{ width: '100%', height: '100%', border: 'none' }}
              sandbox="allow-scripts allow-same-origin allow-popups"
              title={article.title}
            />
          </div>

          {showTranslation && (
            <div style={translationPanelStyle}>
              <div style={translationHeaderStyle}>
                <i className="fas fa-language" style={{ fontSize: 11, color: 'var(--accent-tertiary)' }} />
                <span style={{ fontSize: 11, color: 'var(--text-secondary)', fontWeight: 600 }}>AI 译文</span>
              </div>
              <div ref={translationRef} style={translationContentStyle} onScroll={handleTranslationScroll}>
                {contentLoading ? (
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
                    <i className="fas fa-spinner fa-spin" style={{ color: 'var(--accent)', fontSize: 16 }} />
                  </div>
                ) : hasTranslation ? (
                  <div style={{ fontSize: 14, lineHeight: 1.8, color: 'var(--text-primary)', whiteSpace: 'pre-wrap' }}>
                    {content!.translation}
                  </div>
                ) : (
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-muted)', fontSize: 13 }}>
                    暂无译文
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const overlayStyle: React.CSSProperties = {
  position: 'absolute', top: 0, right: 0, bottom: 0, width: '85%', minWidth: 600, maxWidth: 1400,
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

const toggleBtn: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 5,
  border: '1px solid var(--border)', borderRadius: 6,
  padding: '4px 10px', fontSize: 12, cursor: 'pointer',
  transition: 'var(--transition-fast)',
};

const translationPanelStyle: React.CSSProperties = {
  width: '45%', borderLeft: '1px solid var(--border)',
  display: 'flex', flexDirection: 'column', background: 'var(--bg-secondary)',
};

const translationHeaderStyle: React.CSSProperties = {
  padding: '6px 12px', borderBottom: '1px solid var(--border)',
  display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0,
};

const translationContentStyle: React.CSSProperties = {
  flex: 1, overflowY: 'auto', padding: '16px 20px',
};
