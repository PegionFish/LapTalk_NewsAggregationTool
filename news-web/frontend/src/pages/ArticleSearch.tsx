import { useEffect, useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import type { Article } from '../types';
import { Input, Select, Button, Badge, Loading, Tabs, Tab } from '../components/ui';
import ArticlePane from '../components/ArticlePane';
import CommentPanel from '../components/CommentPanel';
import { decodeHTMLEntities } from '../utils/html';

const PER_PAGE = 50;

// 主题分类 Tab 配置（顺序即展示顺序）
const CATEGORY_TABS = [
  { key: '', label: '全部', icon: 'fa-layer-group', color: 'var(--accent)' },
  { key: '硬件', label: '硬件', icon: 'fa-microchip', color: 'var(--accent-tertiary)' },
  { key: 'AI', label: 'AI', icon: 'fa-brain', color: 'var(--accent)' },
  { key: '游戏', label: '游戏', icon: 'fa-gamepad', color: 'var(--accent-purple)' },
  { key: '移动', label: '移动', icon: 'fa-mobile-screen', color: 'var(--accent-orange)' },
  { key: '发布', label: '发布', icon: 'fa-bullhorn', color: 'var(--accent-tertiary)' },
  { key: '其他', label: '其他', icon: 'fa-ellipsis', color: 'var(--text-muted)' },
];

const SORT_OPTIONS = [
  { value: 'fetched_desc', label: '默认排序' },
  { value: 'score_desc', label: '评分最高' },
  { value: 'score_asc', label: '评分最低' },
  { value: 'date_desc', label: '最新发布' },
];

export default function ArticleSearch() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [articles, setArticles] = useState<Article[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [priority, setPriority] = useState('');
  const [verified, setVerified] = useState('');
  const [topicCategory, setTopicCategory] = useState('');
  const [sort, setSort] = useState('fetched_desc');
  const [categoryStats, setCategoryStats] = useState<Record<string, number>>({});
  const [selected, setSelected] = useState<Article | null>(null);
  const [reading, setReading] = useState<Article | null>(null);
  const [loading, setLoading] = useState(false);
  const [aiAnalysis, setAiAnalysis] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisMeta, setAnalysisMeta] = useState<{ ai_analyzed?: boolean; human_processed?: boolean; translated?: boolean }>({});

  const fetchArticles = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { page, limit: PER_PAGE };
      if (search) params.q = search;
      if (priority) params.priority = priority;
      if (verified === 'yes') params.verified = 'yes';
      else if (verified === 'no') params.verified = 'no';
      if (topicCategory) params.topic_category = topicCategory;
      if (sort && sort !== 'fetched_desc') params.sort = sort;
      const res = await api.searchArticles(params);
      setArticles(res.articles || []);
      setTotal(res.total || 0);
    } catch { setArticles([]); }
    setLoading(false);
  }, [page, search, priority, verified, topicCategory, sort]);

  useEffect(() => { fetchArticles(); }, [fetchArticles]);

  // 加载主题分类统计（首次加载时自动回填 + 查询统计）
  const loadCategoryStats = useCallback(async () => {
    try {
      await api.populateTopicCategories();
      const res = await api.getTopicCategories();
      setCategoryStats(res.categories || {});
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadCategoryStats(); }, [loadCategoryStats]);

  // URL ↔ 选中文章同步：?id=123 自动打开文章详情面板
  useEffect(() => {
    const idParam = searchParams.get('id');
    if (idParam) {
      const aid = parseInt(idParam, 10);
      if (!isNaN(aid) && selected?.id !== aid) {
        // 不在列表中时直接按 ID 获取
        api.getArticle(aid).then(a => setSelected(a)).catch(() => {});
      }
    }
  }, [searchParams]); // 仅在 URL 参数变化时触发（不含 selected）

  // 选中文章变更 → URL 同步
  useEffect(() => {
    const idParam = searchParams.get('id');
    const expectedId = selected ? String(selected.id) : null;
    if (idParam !== expectedId) {
      if (expectedId) {
        setSearchParams({ id: expectedId }, { replace: true });
      } else {
        // 清除 id 参数
        const next = new URLSearchParams(searchParams);
        next.delete('id');
        setSearchParams(next, { replace: true });
      }
    }
  }, [selected]);

  useEffect(() => {
    if (!selected) { setAiAnalysis(''); setAnalysisMeta({}); return; }
    setAiAnalysis('');
    setAnalyzing(true);
    setAnalysisMeta({});
    api.getArticleContent(selected.id).then(c => {
      setAnalysisMeta({
        ai_analyzed: c?.ai_analyzed,
        human_processed: c?.human_processed,
        translated: selected.content_status === 'translated',
      });
      if (c?.ai_summary) {
        setAiAnalysis(c.ai_summary);
        setAnalyzing(false);
      }
    }).catch(() => {});
    api.analyzeArticle(selected.id).then(r => {
      if (r.ok && r.analysis) setAiAnalysis(r.analysis);
    }).catch(() => {}).finally(() => setAnalyzing(false));
  }, [selected?.id]);

  const cacheBadge = (status: string): { icon: string; variant: 'green' | 'blue' | 'red' | 'muted'; tooltip: string } => {
    switch (status) {
      case 'translated': return { icon: 'fa-check-circle', variant: 'green', tooltip: '翻译已就绪' };
      case 'fetched': return { icon: 'fa-check-circle', variant: 'green', tooltip: '内容已缓存' };
      case 'failed': return { icon: 'fa-exclamation-triangle', variant: 'red', tooltip: '下载失败' };
      case 'file': return { icon: 'fa-file-alt', variant: 'blue', tooltip: 'HTML 磁盘缓存' };
      default: return { icon: 'fa-hourglass-half', variant: 'muted', tooltip: '尚未下载内容' };
    }
  };

  const totalPages = Math.ceil(total / PER_PAGE);

  return (
    <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
      {/* 中：文章列表 */}
      <div style={{ flex: 1, overflow: 'auto', padding: 24 }}>
        {/* 工具栏 */}
        <div style={{
          display: 'flex',
          gap: 10,
          marginBottom: 20,
          flexWrap: 'wrap',
          alignItems: 'center',
        }}>
          <Input
            placeholder="搜索标题或关键词..."
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1); }}
            style={{ flex: 1, minWidth: 200 }}
          />
          <Select value={priority} onChange={e => { setPriority(e.target.value); setPage(1); }}>
            <option value="">全部优先级</option>
            <option value="high">高</option>
            <option value="medium">中</option>
            <option value="low">低</option>
          </Select>
          <Select value={verified} onChange={e => { setVerified(e.target.value); setPage(1); }}>
            <option value="">全部状态</option>
            <option value="yes">已审核</option>
            <option value="no">待审核</option>
          </Select>
          <Select value={sort} onChange={e => { setSort(e.target.value); setPage(1); }}>
            {SORT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </Select>
          {loading && <i className="fas fa-spinner fa-spin" style={{ color: 'var(--accent)', fontSize: 14 }} />}
        </div>

        {/* 主题分类 Tab */}
        <Tabs style={{ marginBottom: 16, flexWrap: 'wrap' }}>
          {CATEGORY_TABS.map(t => {
            const count = t.key === '' ? Object.values(categoryStats).reduce((s, n) => s + n, 0) : (categoryStats[t.key] || 0);
            return (
              <Tab
                key={t.key || 'all'}
                active={topicCategory === t.key}
                icon={t.icon}
                color={t.color}
                count={count}
                onClick={() => { setTopicCategory(t.key); setPage(1); }}
              >
                {t.label}
              </Tab>
            );
          })}
        </Tabs>

        {/* 表格 */}
        <div style={{
          background: 'var(--bg-secondary)',
          borderRadius: 'var(--radius-lg)',
          border: '1px solid var(--border)',
          overflow: 'hidden',
        }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{
                borderBottom: '1px solid var(--border)',
                background: 'rgba(0, 0, 0, 0.15)',
              }}>
                <th style={thStyle}>标题</th>
                <th style={{ ...thStyle, width: 80 }}>来源</th>
                <th style={{ ...thStyle, width: 48 }}>语言</th>
                <th style={{ ...thStyle, width: 56 }}>评分</th>
                <th style={{ ...thStyle, width: 40 }}>缓存</th>
                <th style={{ ...thStyle, width: 40 }}>翻译</th>
                <th style={{ ...thStyle, width: 40 }}>分析</th>
                <th style={{ ...thStyle, width: 48 }}>审核</th>
                <th style={{ ...thStyle, width: 72, whiteSpace: 'nowrap' }}>日期</th>
              </tr>
            </thead>
            <tbody>
              {articles.map(a => (
                <tr
                  key={a.id}
                  onClick={() => setSelected(a)}
                  onDoubleClick={() => setReading(a)}
                  style={{
                    cursor: 'pointer',
                    borderBottom: '1px solid var(--border)',
                    background: selected?.id === a.id ? 'rgba(0, 212, 255, 0.06)' : 'transparent',
                    transition: 'background var(--transition-fast)',
                  }}
                  onMouseEnter={e => {
                    if (selected?.id !== a.id) {
                      e.currentTarget.style.background = 'var(--bg-card-hover)';
                    }
                  }}
                  onMouseLeave={e => {
                    if (selected?.id !== a.id) {
                      e.currentTarget.style.background = 'transparent';
                    }
                  }}
                >
                  <td style={{
                    padding: '10px 12px',
                    fontWeight: selected?.id === a.id ? 600 : 400,
                    maxWidth: 350,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}>
                    {decodeHTMLEntities(a.title)}
                  </td>
                  <td style={{ padding: '10px 12px', color: 'var(--text-secondary)', fontSize: 11 }}>{a.source}</td>
                  <td style={{ padding: '10px 12px', textAlign: 'center', fontSize: 11 }}>
                    <Badge
                      variant={a.content_lang === 'en' ? 'green' : a.content_lang === 'zh' ? 'purple' : 'muted'}
                    >
                      {a.content_lang?.toUpperCase() || '?'}
                    </Badge>
                  </td>
                  <td style={{
                    padding: '10px 12px',
                    textAlign: 'center',
                    color: a.score >= 70 ? 'var(--accent-tertiary)' : a.score >= 40 ? 'var(--accent-orange)' : 'var(--text-muted)',
                    fontWeight: 600,
                    fontSize: 12,
                  }}>
                    {Math.round(a.score)}
                  </td>
                  <td style={{ padding: '10px 12px', textAlign: 'center', fontSize: 12 }}>
                    {(() => { const b = cacheBadge(a.content_status); return <i className={`fas ${b.icon}`} style={{ color: `var(--accent-${b.variant === 'green' ? 'tertiary' : b.variant === 'red' ? 'red' : b.variant === 'blue' ? '' : 'muted'})` }} title={b.tooltip} />; })()}
                  </td>
                  <td style={{ padding: '10px 12px', textAlign: 'center', fontSize: 12 }}>
                    <i className={`fas ${a.has_translation ? 'fa-check-circle' : 'fa-minus-circle'}`}
                       style={{ color: a.has_translation ? 'var(--accent-tertiary)' : 'var(--text-muted)', fontSize: 11 }}
                       title={a.has_translation ? '已翻译' : '未翻译'} />
                  </td>
                  <td style={{ padding: '10px 12px', textAlign: 'center', fontSize: 12 }}>
                    <i className={`fas ${a.ai_analyzed ? 'fa-check-circle' : 'fa-minus-circle'}`}
                       style={{ color: a.ai_analyzed ? 'var(--accent)' : 'var(--text-muted)', fontSize: 11 }}
                       title={a.ai_analyzed ? '已分析' : '未分析'} />
                  </td>
                  <td style={{ padding: '10px 12px', textAlign: 'center', fontSize: 11 }}>
                    <Badge
                      variant={a.human_processed ? 'blue' : a.verified ? 'green' : 'muted'}
                    >
                      {a.human_processed ? '人工' : a.verified ? '已审' : '待审'}
                    </Badge>
                  </td>
                  <td style={{ padding: '10px 12px', color: 'var(--text-muted)', fontSize: 11, whiteSpace: 'nowrap' }}>
                    {a.published?.slice(5, 10) || a.fetched?.slice(5, 10)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* 分页 */}
        {totalPages > 1 && (
          <div style={{
            display: 'flex',
            justifyContent: 'center',
            gap: 10,
            marginTop: 20,
          }}>
            <Button
              variant="ghost"
              size="sm"
              icon="fa-chevron-left"
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
            >
              上一页
            </Button>
            <span style={{
              fontSize: 12,
              color: 'var(--text-secondary)',
              padding: '6px 12px',
              display: 'flex',
              alignItems: 'center',
            }}>
              {page} / {totalPages} · 共 {total} 条
            </span>
            <Button
              variant="ghost"
              size="sm"
              icon="fa-chevron-right"
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
            >
              下一页
            </Button>
          </div>
        )}
      </div>

      {/* 右：详情面板 */}
      {selected && (
        <div style={{
          width: 400,
          minWidth: 400,
          background: 'var(--bg-secondary)',
          borderLeft: '1px solid var(--border)',
          overflow: 'auto',
          padding: 24,
          display: 'flex',
          flexDirection: 'column',
          animation: 'slideInRight 0.2s ease',
        }}>
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            marginBottom: 16,
          }}>
            <h3 style={{
              fontSize: 16,
              fontWeight: 600,
              lineHeight: 1.4,
              margin: 0,
              flex: 1,
              paddingRight: 12,
            }}>
              {decodeHTMLEntities(selected.title)}
            </h3>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <button
                onClick={() => {
                  const url = `${window.location.origin}/articles?id=${selected.id}`;
                  navigator.clipboard.writeText(url).then(() => {
                    // 临时切换图标表示已复制
                    const btn = document.getElementById('copy-link-btn');
                    if (btn) {
                      const icon = btn.querySelector('i');
                      if (icon) { icon.className = 'fas fa-check'; }
                      setTimeout(() => {
                        if (icon) { icon.className = 'fas fa-link'; }
                      }, 1500);
                    }
                  }).catch(() => {});
                }}
                id="copy-link-btn"
                title="复制文章链接，分享给团队成员"
                style={{
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                  padding: '6px 8px',
                  fontSize: 12,
                  transition: 'all var(--transition-fast)',
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.background = 'var(--bg-card-hover)';
                  e.currentTarget.style.color = 'var(--accent)';
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.background = 'var(--bg-card)';
                  e.currentTarget.style.color = 'var(--text-muted)';
                }}
              >
                <i className="fas fa-link" />
              </button>
              <button
                onClick={() => setSelected(null)}
                style={{
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                  padding: '6px 8px',
                  fontSize: 12,
                  transition: 'all var(--transition-fast)',
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.background = 'var(--bg-card-hover)';
                  e.currentTarget.style.color = 'var(--text-primary)';
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.background = 'var(--bg-card)';
                  e.currentTarget.style.color = 'var(--text-muted)';
                }}
              >
                <i className="fas fa-times" />
              </button>
            </div>
          </div>

          {/* 元信息 */}
          <div style={{
            display: 'flex',
            gap: 14,
            marginBottom: 14,
            flexWrap: 'wrap',
            fontSize: 12,
            color: 'var(--text-secondary)',
            alignItems: 'center',
          }}>
            <span><i className="fas fa-newspaper" style={{ marginRight: 4 }} />{selected.source}</span>
            <span><i className="fas fa-calendar" style={{ marginRight: 4 }} />{selected.fetched?.slice(0, 10)}</span>
            {selected.topic_category && (
              <Badge variant="blue" icon="fa-folder">{selected.topic_category}</Badge>
            )}
            <span style={{
              color: selected.score >= 70 ? 'var(--accent-tertiary)' : selected.score >= 40 ? 'var(--accent-orange)' : 'var(--text-muted)',
              fontWeight: 600,
            }}>
              <i className="fas fa-star" style={{ marginRight: 4 }} />
              {Math.round(selected.score)}
            </span>
          </div>

          {/* 缓存状态 */}
          {(() => { const b = cacheBadge(selected.content_status); return (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              marginBottom: 14,
              fontSize: 12,
            }}>
              <Badge variant={b.variant} icon={b.icon}>
                {b.tooltip}
              </Badge>
              {selected.content_fetched_at && (
                <span style={{ color: 'var(--text-muted)', marginLeft: 'auto', fontSize: 11 }}>
                  <i className="fas fa-clock" style={{ marginRight: 4 }} />
                  {selected.content_fetched_at.slice(0, 10)}
                </span>
              )}
            </div>
          ); })()}

          {/* 关键词 */}
          {selected.keywords?.length > 0 && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
              {selected.keywords.map(k => (
                <span key={k} className="ui-tag">{k}</span>
              ))}
            </div>
          )}

          {/* 操作按钮 */}
          <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
            <Button
              variant="primary"
              size="sm"
              icon="fa-book-open"
              onClick={() => setReading(selected)}
            >
              阅读全文
            </Button>
            <Button
              variant="ghost"
              size="sm"
              icon="fa-external-link-alt"
              onClick={() => window.open(selected.url, '_blank')}
            >
              原文
            </Button>
          </div>

          {/* 事件链接 */}
          {selected.event && (
            <a
              href={`/workspace?event=${selected.event.id}`}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                fontSize: 12,
                color: 'var(--accent)',
                textDecoration: 'none',
                marginBottom: 14,
                padding: '8px 12px',
                background: 'rgba(0, 212, 255, 0.06)',
                borderRadius: 8,
                border: '1px solid rgba(0, 212, 255, 0.15)',
                transition: 'all var(--transition-fast)',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.background = 'rgba(0, 212, 255, 0.12)';
                e.currentTarget.style.borderColor = 'rgba(0, 212, 255, 0.3)';
              }}
              onMouseLeave={e => {
                e.currentTarget.style.background = 'rgba(0, 212, 255, 0.06)';
                e.currentTarget.style.borderColor = 'rgba(0, 212, 255, 0.15)';
              }}
            >
              <i className="fas fa-diagram-project" />
              查看所属事件: {selected.event.title}
            </a>
          )}

          <div style={{
            borderTop: '1px solid var(--border)',
            margin: '16px 0',
          }} />

          {/* 标注状态徽章 */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
            {analysisMeta.ai_analyzed ? (
              <Badge variant="blue" icon="fa-brain">已分析</Badge>
            ) : analyzing ? (
              <Badge variant="orange" icon="fa-spinner">分析中</Badge>
            ) : (
              <Badge variant="muted" icon="fa-brain">未分析</Badge>
            )}
            {analysisMeta.translated ? (
              <Badge variant="green" icon="fa-language">已翻译</Badge>
            ) : (
              <Badge variant="muted" icon="fa-language">未翻译</Badge>
            )}
            {analysisMeta.human_processed ? (
              <Badge variant="blue" icon="fa-user-check">人工已处理</Badge>
            ) : (
              <Badge variant="muted" icon="fa-user-edit">待审核</Badge>
            )}
          </div>

          {/* AI 分析摘要 */}
          <div style={{
            fontSize: 12,
            color: 'var(--text-muted)',
            marginBottom: 8,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}>
            <i className="fas fa-robot" style={{ color: 'var(--accent)' }} />
            AI 分析解读
          </div>
          {analyzing && !aiAnalysis ? (
            <div style={{
              fontSize: 12,
              color: 'var(--text-muted)',
              padding: '8px 12px',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}>
              <i className="fas fa-spinner fa-spin" style={{ color: 'var(--accent)', fontSize: 11 }} />
              分析中...
            </div>
          ) : aiAnalysis ? (
            <div style={{
              fontSize: 12,
              lineHeight: 1.8,
              color: 'var(--text-secondary)',
              whiteSpace: 'pre-wrap',
              flex: 1,
              overflow: 'auto',
              background: 'var(--bg-card)',
              borderRadius: 8,
              padding: 14,
              border: '1px solid var(--border)',
            }}>
              {aiAnalysis}
            </div>
          ) : (
            <div style={{
              fontSize: 12,
              color: 'var(--text-muted)',
              padding: 12,
              background: 'var(--bg-card)',
              borderRadius: 8,
              border: '1px solid var(--border)',
            }}>
              该文章暂无法分析（可能尚未完成内容提取）。
            </div>
          )}

          {/* 分隔线 + 审核评语 */}
          <div style={{ borderTop: '1px solid var(--border)', margin: '16px 0' }} />
          <CommentPanel articleId={selected.id} />
        </div>
      )}

      <ArticlePane article={reading} onClose={() => setReading(null)} />
    </div>
  );
}

const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '10px 12px',
  fontWeight: 600,
  fontSize: 11,
  color: 'var(--text-muted)',
  textTransform: 'uppercase',
  letterSpacing: 0.5,
};
