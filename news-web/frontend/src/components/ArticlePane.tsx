import { useEffect, useState } from 'react';
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

  useEffect(() => {
    if (!article) { setContent(null); return; }
    setLoading(true);
    setContent(null);
    api.getArticleContent(article.id)
      .then((c: ArticleContent) => setContent(c))
      .catch(() => setContent(null))
      .finally(() => setLoading(false));
  }, [article?.id]);

  if (!article) return null;

  const hasTranslation = content?.translation && content.translation.length > 0;
  const isEnglish = content?.lang === 'en';

  const handleScroll = (e: React.UIEvent<HTMLDivElement>, side: 'left' | 'right') => {
    if (synced) return;
    setSynced(true);
    const other = document.getElementById(side === 'left' ? 'pane-right' : 'pane-left');
    if (other) other.scrollTop = (e.target as HTMLDivElement).scrollTop;
    setTimeout(() => setSynced(false), 50);
  };

  return (
    <div style={{
      width: hasTranslation ? 700 : 420, minWidth: 360, background: 'var(--bg-secondary)',
      borderLeft: '1px solid var(--border)', display: 'flex', flexDirection: 'column',
      overflow: 'hidden', transition: 'width var(--transition-base)',
    }}>
      {/* 顶栏 */}
      <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
        <span style={{ fontSize: 13, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
          {article.title.slice(0, 60)}
        </span>
        <button onClick={onClose} style={iconBtnStyle} title="关闭">
          <i className="fas fa-times" />
        </button>
      </div>

      {/* 元数据条 */}
      <div style={{ padding: '6px 14px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 12, fontSize: 11, color: 'var(--text-secondary)', flexShrink: 0 }}>
        {article.source && <span>📰 {article.source}</span>}
        {article.fetched && <span>📅 {article.fetched.slice(0, 10)}</span>}
        {content?.lang && <span>🌐 {content.lang.toUpperCase()}</span>}
        {content?.source === 'local' && <span style={{ color: 'var(--accent-tertiary)' }}>💾 缓存</span>}
        {isEnglish && hasTranslation && (
          <button onClick={() => setShowTrans(!showTrans)}
            style={{ ...tagBtnStyle, background: showTrans ? 'var(--accent)' : 'var(--bg-card)',
                     color: showTrans ? '#000' : 'var(--text-secondary)' }}>
            {showTrans ? '译文' : '原文'}
          </button>
        )}
      </div>

      {/* 内容区 */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex' }}>
        {loading ? (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
            <i className="fas fa-spinner fa-spin" /> 加载中...
          </div>
        ) : !content?.content ? (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 13, padding: 20, textAlign: 'center' }}>
            文章内容暂不可用。该文章可能尚未完成内容抓取。
            <br /><a href={article.url} target="_blank" rel="noopener" style={{ color: 'var(--accent)', marginTop: 8 }}>打开原文 →</a>
          </div>
        ) : hasTranslation ? (
          // 对照模式
          <div style={{ flex: 1, display: 'flex' }}>
            <div id="pane-left" onScroll={e => handleScroll(e, 'left')}
              style={{ flex: 1, overflow: 'auto', padding: 14, fontSize: 13, lineHeight: 1.8 }}>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 8 }}>📄 原文 ({content.lang.toUpperCase()})</div>
              <div style={{ whiteSpace: 'pre-wrap' }}>{content.content}</div>
            </div>
            <div style={{ width: 1, background: 'var(--border)' }} />
            <div id="pane-right" onScroll={e => handleScroll(e, 'right')}
              style={{ flex: showTrans ? 1 : 0, overflow: showTrans ? 'auto' : 'hidden', padding: 14, fontSize: 13, lineHeight: 1.8 }}>
              <div style={{ fontSize: 10, color: 'var(--accent)', marginBottom: 8 }}>🌐 译文</div>
              <div style={{ whiteSpace: 'pre-wrap' }}>{content.translation}</div>
            </div>
          </div>
        ) : (
          // 单栏原文
          <div style={{ flex: 1, overflow: 'auto', padding: 14 }}>
            <div style={{ fontSize: 13, lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>{content.content}</div>
          </div>
        )}
      </div>

      {/* 底栏操作 */}
      <div style={{ padding: '8px 14px', borderTop: '1px solid var(--border)', display: 'flex', gap: 8, flexShrink: 0 }}>
        <a href={article.url} target="_blank" rel="noopener noreferrer"
          style={{ ...actionLinkStyle, color: 'var(--accent)' }}>
          <i className="fas fa-external-link-alt" /> 打开原文
        </a>
        <a href={`/articles/${article.id}`} target="_blank" rel="noopener noreferrer"
          style={{ ...actionLinkStyle, color: 'var(--text-secondary)' }}>
          <i className="fas fa-expand" /> 独立阅读
        </a>
      </div>
    </div>
  );
}

const iconBtnStyle: React.CSSProperties = {
  background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer',
  fontSize: 14, padding: 4, borderRadius: 4,
};

const tagBtnStyle: React.CSSProperties = {
  border: 'none', borderRadius: 4, padding: '1px 8px', fontSize: 10,
  cursor: 'pointer', fontWeight: 600, transition: 'var(--transition-fast)',
};

const actionLinkStyle: React.CSSProperties = {
  fontSize: 11, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4,
};
