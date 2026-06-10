import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type { Article } from '../types';

interface ArticleContent {
  url: string; content: string; translation: string;
  lang: string; status: string; source: string;
}

interface Props {
  article: Article | null;
  onClose: () => void;
}

export default function ArticlePane({ article, onClose }: Props) {
  const [content, setContent] = useState<ArticleContent | null>(null);
  const [loading, setLoading] = useState(false);
  const [showTrans, setShowTrans] = useState(true);
  const [synced, setSynced] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [panelWidth, setPanelWidth] = useState(440);
  const leftRef = useRef<HTMLDivElement>(null);
  const rightRef = useRef<HTMLDivElement>(null);

  useEffect(() => { setPanelWidth(expanded ? Math.min(window.innerWidth * 0.65, 800) : 440); }, [expanded]);

  useEffect(() => {
    if (!article) { setContent(null); return; }
    setLoading(true);
    setContent(null);
    setExpanded(false);
    api.getArticleContent(article.id)
      .then((c: ArticleContent) => setContent(c))
      .catch(() => setContent(null))
      .finally(() => setLoading(false));
  }, [article?.id]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    if (article) { window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler); }
  }, [article, onClose]);

  if (!article) return null;

  const hasTranslation = content?.translation && content.translation.length > 0;
  const isEnglish = content?.lang === 'en';

  const handleScroll = (e: React.UIEvent<HTMLDivElement>, side: 'left' | 'right') => {
    if (synced) return;
    setSynced(true);
    const other = (side === 'left' ? rightRef : leftRef).current;
    if (other) other.scrollTop = (e.target as HTMLDivElement).scrollTop;
    setTimeout(() => setSynced(false), 50);
  };

  return (
    <div style={{ ...overlayStyle, width: panelWidth }}>
      {/* 半透明遮罩 — 点击关闭 */}
      <div onClick={onClose} style={{ position: 'absolute', inset: 0, zIndex: 0 }} />

      {/* 面板主体 */}
      <div style={{ ...panelStyle, width: panelWidth }}>
        {/* 顶栏 */}
        <div style={headerStyle}>
          <span style={{ fontSize: 13, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
            {article.title.slice(0, 70)}
          </span>
          <div style={{ display: 'flex', gap: 4 }}>
            {isEnglish && hasTranslation && (
              <button onClick={() => setShowTrans(!showTrans)} title={showTrans ? '只看原文' : '显示译文'}
                style={{ ...miniBtn, background: showTrans ? 'rgba(0,212,255,0.15)' : 'var(--bg-card)' }}>
                {showTrans ? '对照' : '原文'}
              </button>
            )}
            {hasTranslation && (
              <button onClick={() => setExpanded(!expanded)} title={expanded ? '收起' : '展开'}
                style={miniBtn}>
                <i className={`fas fa-${expanded ? 'compress' : 'expand'}`} />
              </button>
            )}
            <button onClick={onClose} style={{ ...miniBtn, fontSize: 15 }} title="关闭 (Esc)">
              <i className="fas fa-times" />
            </button>
          </div>
        </div>

        {/* 元数据条 */}
        <div style={metaStyle}>
          {article.source && <span>📰 {article.source}</span>}
          {article.fetched && <span>📅 {article.fetched.slice(0, 10)}</span>}
          {content?.lang && <span>🌐 {content.lang.toUpperCase()}</span>}
          {content?.source === 'local' && <span style={{ color: 'var(--accent-tertiary)' }}>💾 缓存</span>}
        </div>

        {/* 内容区 */}
        <div style={{ flex: 1, overflow: 'hidden', display: 'flex', minHeight: 0 }}>
          {loading ? (
            <div style={centerStyle}><i className="fas fa-spinner fa-spin" /> 加载中...</div>
          ) : !content?.content ? (
            <div style={centerStyle}>
              <div style={{ textAlign: 'center', fontSize: 12, lineHeight: 1.8 }}>
                内容暂不可用 — 该文章可能尚未完成抓取。
                <br />
                <a href={article.url} target="_blank" rel="noopener" style={extLink}>
                  打开原文 <i className="fas fa-external-link-alt" />
                </a>
              </div>
            </div>
          ) : hasTranslation ? (
            <div style={{ flex: 1, display: 'flex' }}>
              <div ref={leftRef} onScroll={e => handleScroll(e, 'left')}
                style={scrollCol}>
                <div style={colLabel}>📄 原文 ({content.lang.toUpperCase()})</div>
                <div style={prose}>{content.content}</div>
              </div>
              <div style={{ width: 1, background: 'var(--border)' }} />
              <div ref={rightRef} onScroll={e => handleScroll(e, 'right')}
                style={{ ...scrollCol, flex: showTrans ? 1 : 0.001, overflow: showTrans ? 'auto' : 'hidden' }}>
                <div style={{ ...colLabel, color: 'var(--accent-tertiary)' }}>🌐 译文</div>
                <div style={prose}>{content.translation}</div>
              </div>
            </div>
          ) : (
            <div style={scrollCol}>
              <div style={prose}>{content.content}</div>
            </div>
          )}
        </div>

        {/* 底栏 */}
        <div style={footerStyle}>
          <a href={article.url} target="_blank" rel="noopener noreferrer" style={{ ...actionLink, color: 'var(--accent)' }}>
            <i className="fas fa-external-link-alt" /> 打开原文
          </a>
          <a href={`/articles/${article.id}`} target="_blank" rel="noopener noreferrer" style={{ ...actionLink, color: 'var(--text-secondary)' }}>
            <i className="fas fa-expand" /> 独立阅读
          </a>
          <div style={{ flex: 1 }} />
          <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>Esc 关闭</div>
        </div>
      </div>
    </div>
  );
}

const overlayStyle: React.CSSProperties = {
  position: 'absolute', top: 0, right: 0, bottom: 0,
  zIndex: 50, transition: 'width var(--transition-base)',
};

const panelStyle: React.CSSProperties = {
  position: 'absolute', top: 0, right: 0, bottom: 0,
  background: 'var(--bg-secondary)', borderLeft: '1px solid var(--border)',
  display: 'flex', flexDirection: 'column',
  boxShadow: '-8px 0 24px rgba(0,0,0,0.4)',
  zIndex: 1, transition: 'width var(--transition-base)',
  animation: 'slideInRight 0.2s ease-out',
};

const headerStyle: React.CSSProperties = {
  padding: '10px 14px', borderBottom: '1px solid var(--border)',
  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  flexShrink: 0, gap: 8,
};

const metaStyle: React.CSSProperties = {
  padding: '5px 14px', display: 'flex', gap: 12, fontSize: 11,
  color: 'var(--text-secondary)', flexShrink: 0, flexWrap: 'wrap',
};

const scrollCol: React.CSSProperties = {
  flex: 1, overflow: 'auto', padding: 14,
};

const prose: React.CSSProperties = {
  fontSize: 13, lineHeight: 1.8, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
};

const colLabel: React.CSSProperties = {
  fontSize: 10, color: 'var(--text-muted)', marginBottom: 8,
  textTransform: 'uppercase', letterSpacing: 0.5,
};

const centerStyle: React.CSSProperties = {
  flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
  color: 'var(--text-muted)', fontSize: 13,
};

const footerStyle: React.CSSProperties = {
  padding: '8px 14px', borderTop: '1px solid var(--border)',
  display: 'flex', gap: 12, alignItems: 'center', flexShrink: 0,
};

const actionLink: React.CSSProperties = {
  fontSize: 11, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4,
};

const extLink: React.CSSProperties = {
  color: 'var(--accent)', marginTop: 8, display: 'inline-block', fontSize: 12,
};

const miniBtn: React.CSSProperties = {
  background: 'var(--bg-card)', border: '1px solid var(--border)',
  borderRadius: 4, padding: '3px 8px', color: 'var(--text-secondary)',
  cursor: 'pointer', fontSize: 11, transition: 'var(--transition-fast)',
};
