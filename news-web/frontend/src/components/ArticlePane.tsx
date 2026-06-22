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
  has_pdf?: boolean;
  status?: string;
  challenge_type?: string;
  challenge_reason?: string;
}

export default function ArticlePane({ article, onClose }: Props) {
  const [loaded, setLoaded] = useState(false);
  const [showTranslation, setShowTranslation] = useState(false);
  const [content, setContent] = useState<ArticleContent | null>(null);
  const [contentLoading, setContentLoading] = useState(false);
  const [isFallback, setIsFallback] = useState(false);
  const [isChallenge, setIsChallenge] = useState(false);
  const [challengeType, setChallengeType] = useState('');
  const [challengeReason, setChallengeReason] = useState('');
  const [originalUrl, setOriginalUrl] = useState('');
  const [isRetrying, setIsRetrying] = useState(false);
  const [pasteMode, setPasteMode] = useState(false);
  const [pasteContent, setPasteContent] = useState('');
  const [saveStatus, setSaveStatus] = useState('');
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const translationRef = useRef<HTMLDivElement>(null);
  const syncingRef = useRef(false);
  const fallbackCheckDone = useRef(false);

  useEffect(() => {
    setLoaded(false);
    setShowTranslation(false);
    setContent(null);
    setIsFallback(false);
    setIsChallenge(false);
    setChallengeType('');
    setChallengeReason('');
    setOriginalUrl('');
    setPasteMode(false);
    setPasteContent('');
    setSaveStatus('');
    setIsRetrying(false);
    fallbackCheckDone.current = false;
  }, [article?.id]);

  useEffect(() => {
    if (!article) return;
    setContentLoading(true);
    api.getArticleContent(article.id)
      .then(c => {
        setContent({ translation: c.translation, lang: c.lang, has_pdf: c.has_pdf, status: c.status, challenge_type: (c as any).challenge_type, challenge_reason: (c as any).challenge_reason });
        if (c.status === 'challenge') {
          setIsChallenge(true);
          setChallengeType((c as any).challenge_type || 'unknown');
          setChallengeReason((c as any).challenge_reason || '需要人机验证');
        }
      })
      .catch(() => setContent(null))
      .finally(() => setContentLoading(false));
  }, [article?.id]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    if (article) { window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler); }
  }, [article, onClose]);

  const handleIframeLoad = useCallback(() => {
    setLoaded(true);
    if (fallbackCheckDone.current) return;
    fallbackCheckDone.current = true;

    try {
      const iframe = iframeRef.current;
      if (!iframe?.contentDocument) return;
      const doc = iframe.contentDocument;
      const body = doc.body?.textContent || '';

      // 检测 challenge meta 标签（后端 fallback 页标记）
      const chalMeta = doc.querySelector('meta[name="x-challenge"]');
      if (chalMeta) {
        setIsChallenge(true);
        setChallengeType(chalMeta.getAttribute('content') || 'unknown');
        setChallengeReason(doc.body?.querySelector('h3')?.textContent || '需要人机验证');
        return;
      }

      if (body.includes('内容暂未缓存') || body.includes('无法获取此页面')) {
        setIsFallback(true);
        const links = doc.querySelectorAll('a');
        links.forEach(a => {
          if (a.href && !a.href.includes('localhost') && !a.href.startsWith('http://localhost')) {
            setOriginalUrl(a.href);
          }
        });
      }
    } catch {}
  }, []);

  const handleOpenOriginal = useCallback(() => {
    const url = originalUrl || article?.url;
    if (url) window.open(url, '_blank');
  }, [originalUrl, article]);

  const handleRetry = useCallback(async () => {
    if (!article) return;
    setIsRetrying(true);
    try {
      const res = await api.retryPlaywrightCapture(article.id);
      if (res.ok) {
        // 重试成功 — 刷新 iframe
        fallbackCheckDone.current = false;
        setIsChallenge(false);
        setIsFallback(false);
        setLoaded(false);
        if (iframeRef.current) {
          iframeRef.current.src = `/api/articles/${article.id}/html?t=${Date.now()}`;
        }
      } else if ((res as any).challenge) {
        setSaveStatus('验证未通过，请重试或手动粘贴内容');
      } else {
        setSaveStatus(res.error || '重试失败');
      }
    } catch {
      setSaveStatus('网络错误');
    } finally {
      setIsRetrying(false);
    }
  }, [article]);

  const handlePasteSave = useCallback(async () => {
    if (!article || pasteContent.length < 50) {
      setSaveStatus('内容太短，请粘贴完整的文章内容');
      return;
    }
    try {
      const res = await api.cacheArticleHtml(article.id, pasteContent);
      if (res.ok) {
        setSaveStatus('已保存！刷新页面加载内容...');
        setTimeout(() => {
          fallbackCheckDone.current = false;
          setIsChallenge(false);
          setPasteMode(false);
          setLoaded(false);
          if (iframeRef.current) {
            iframeRef.current.src = `/api/articles/${article.id}/html?t=${Date.now()}`;
          }
        }, 1000);
      } else {
        setSaveStatus('保存失败');
      }
    } catch {
      setSaveStatus('网络错误');
    }
  }, [article, pasteContent]);

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

    // 标记是否已处理过 load 事件，防止重复触发
    let handled = false;

    const onLoad = () => {
      if (handled) return;
      handled = true;
      handleIframeLoad();
      try {
        iframe.contentDocument?.addEventListener('scroll', handleIframeScroll);
      } catch {}
    };

    // 修复竞态条件：如果 iframe 在绑定监听器之前已经加载完毕，直接触发
    if (iframe.contentDocument?.readyState === 'complete' || iframe.contentDocument?.readyState === 'interactive') {
      onLoad();
    } else {
      iframe.addEventListener('load', onLoad);
    }

    return () => {
      handled = true;
      iframe.removeEventListener('load', onLoad);
      try {
        iframe.contentDocument?.removeEventListener('scroll', handleIframeScroll);
      } catch {}
    };
  }, [handleIframeLoad, handleIframeScroll]);

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

          {/* 内容获取失败时，显示重试和原文按钮 */}
          {isFallback && (
            <>
              <span style={{ fontSize: 11, color: '#e68a00', fontWeight: 500 }}>
                <i className="fas fa-exclamation-triangle" style={{ marginRight: 3 }} />
                无法获取
              </span>
              <button onClick={handleOpenOriginal} style={openOriginalBtn} title="在原站阅读">
                <i className="fas fa-external-link-alt" />
                <span>原文</span>
              </button>
            </>
          )}

          {/* 人机验证状态 */}
          {isChallenge && (
            <>
              <span style={{ fontSize: 11, color: '#e68a00', fontWeight: 500 }}>
                <i className="fas fa-shield-halved" style={{ marginRight: 3 }} />
                需验证
              </span>
              <button onClick={handleOpenOriginal} style={openOriginalBtn} title="打开原站验证">
                <i className="fas fa-external-link-alt" />
                <span>验证</span>
              </button>
            </>
          )}

          {/* PDF 下载按钮 */}
          {content?.has_pdf && (
            <a href={api.getArticlePdfUrl(article.id)} target="_blank" rel="noopener noreferrer"
              style={pdfBtn} title="下载 PDF 快照">
              <i className="fas fa-file-pdf" />
              <span>PDF</span>
            </a>
          )}

          {article.url && !isFallback && !isChallenge && (
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

          {/* fallback 状态 — iframe 已加载但内容是"内容暂未缓存" */}
          {isFallback && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-primary)', zIndex: 2, gap: 12 }}>
              <i className="fas fa-globe" style={{ fontSize: 40, color: '#ccc' }} />
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', textAlign: 'center', lineHeight: 1.6 }}>
                服务器无法直接获取此页面<br />
                <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>已自动尝试 HTTP + 浏览器渲染两种方式</span>
              </div>
              <button onClick={handleOpenOriginal} style={{
                ...openOriginalBtn,
                padding: '10px 24px', fontSize: 14,
              }}>
                <i className="fas fa-external-link-alt" />
                <span>在浏览器中打开原文</span>
              </button>
              {content?.has_pdf && (
                <a href={api.getArticlePdfUrl(article.id)} target="_blank" rel="noopener noreferrer"
                  style={{ ...openOriginalBtn, background: '#e8e8e8', color: '#333' }}>
                  <i className="fas fa-file-pdf" />
                  <span>查看 PDF 快照</span>
                </a>
              )}
            </div>
          )}

          {/* 人机验证状态 — 网站需要验证身份才能访问 */}
          {isChallenge && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-primary)', zIndex: 2, gap: 14, padding: 32 }}>
              <i className="fas fa-shield-halved" style={{ fontSize: 40, color: '#e68a00' }} />
              <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)' }}>
                需要人机验证
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', textAlign: 'center', lineHeight: 1.6, maxWidth: 400 }}>
                {challengeReason || '该网站使用了反爬虫验证，请用你的浏览器手动打开完成验证'}
              </div>

              {/* 打开原站验证 */}
              <button onClick={handleOpenOriginal} style={{
                ...openOriginalBtn, padding: '10px 24px', fontSize: 14,
              }}>
                <i className="fas fa-external-link-alt" />
                <span>打开原站验证</span>
              </button>

              {/* 重试按钮 */}
              <button onClick={handleRetry} disabled={isRetrying} style={{
                ...openOriginalBtn, background: 'var(--bg-card)', color: 'var(--text-primary)',
                border: '1px solid var(--border)', opacity: isRetrying ? 0.6 : 1,
              }}>
                <i className={`fas ${isRetrying ? 'fa-spinner fa-spin' : 'fa-redo'}`} />
                <span>{isRetrying ? '重试中...' : '已通过验证，重新获取'}</span>
              </button>

              {/* 手动粘贴内容 */}
              {!pasteMode ? (
                <button onClick={() => setPasteMode(true)} style={{
                  ...openOriginalBtn, background: 'transparent', color: 'var(--text-muted)',
                  border: '1px dashed var(--border)', fontSize: 12,
                }}>
                  <i className="fas fa-paste" />
                  <span>手动粘贴内容</span>
                </button>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%', maxWidth: 500 }}>
                  <textarea
                    value={pasteContent}
                    onChange={e => setPasteContent(e.target.value)}
                    placeholder="将文章内容粘贴到这里..."
                    style={{ width: '100%', minHeight: 120, padding: 10, fontSize: 13, border: '1px solid var(--border)', borderRadius: 8, resize: 'vertical', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
                  />
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button onClick={handlePasteSave} style={{
                      ...openOriginalBtn, padding: '8px 16px', fontSize: 13,
                    }}>
                      <i className="fas fa-save" />
                      <span>保存到缓存</span>
                    </button>
                    <button onClick={() => setPasteMode(false)} style={{
                      background: 'none', border: '1px solid var(--border)', borderRadius: 6,
                      padding: '8px 16px', fontSize: 12, cursor: 'pointer', color: 'var(--text-muted)',
                    }}>
                      取消
                    </button>
                  </div>
                  {saveStatus && <span style={{ fontSize: 12, color: saveStatus.includes('已保存') ? 'var(--accent-tertiary)' : '#e68a00' }}>{saveStatus}</span>}
                </div>
              )}
            </div>
          )}

          <div style={{ flex: 1, position: 'relative', background: '#fff', display: isFallback || isChallenge ? 'none' : undefined }}>
            <iframe
              ref={iframeRef}
              src={`/api/articles/${article.id}/html`}
              style={{ width: '100%', height: '100%', border: 'none' }}
              sandbox="allow-same-origin allow-popups"
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

const openOriginalBtn: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 6,
  background: 'var(--accent)', color: '#fff', border: 'none',
  borderRadius: 6, padding: '6px 14px', fontSize: 12,
  cursor: 'pointer', textDecoration: 'none',
  fontWeight: 500,
};

const pdfBtn: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 5,
  background: 'var(--bg-card)', color: '#d32f2f', border: '1px solid #ffcdd2',
  borderRadius: 6, padding: '4px 10px', fontSize: 12,
  cursor: 'pointer', textDecoration: 'none',
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
