import { useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../api/client';
import type { FetchOverview, FetchSource, FetchLog, FailedArticle, FetchArticleItem, BatchRetryState } from '../types';
import { Card, Button, Badge, Table, Tabs, Tab, StatCard, Loading } from '../components/ui';

const emptyOverview: FetchOverview = {
  rss: { total_sources: 0, healthy: 0, degraded: 0, failing: 0, last_run: null, articles_today: 0 },
  hotlist: { total_sources: 0, healthy: 0, degraded: 0, failing: 0, last_run: null, articles_today: 0 },
  cache: { total_articles: 0, cached: 0, pending: 0, failed: 0, cached_pct: 0 },
};

const emptyBatch: BatchRetryState = { running: false, total: 0, done: 0, failed: 0, current: '', log: [] };

const typeLabels: Record<string, string> = { rss: 'RSS', hotlist: '平台热榜', bilibili: 'B站视频' };

const healthVariant: Record<string, 'green' | 'orange' | 'red'> = {
  healthy: 'green',
  degraded: 'orange',
  failing: 'red',
};

const statusVariant: Record<string, 'green' | 'blue' | 'orange' | 'red'> = {
  fetched: 'green',
  translated: 'blue',
  pending: 'orange',
  failed: 'red',
};

export default function FetchMonitor() {
  const [overview, setOverview] = useState<FetchOverview>(emptyOverview);
  const [sources, setSources] = useState<FetchSource[]>([]);
  const [logs, setLogs] = useState<FetchLog[]>([]);
  const [loading, setLoading] = useState(true);

  const [sourceFilter, setSourceFilter] = useState('');
  const [expandedSource, setExpandedSource] = useState<string | null>(null);
  const [sourceHistory, setSourceHistory] = useState<FetchLog[]>([]);
  const [sourceArticles, setSourceArticles] = useState<FetchArticleItem[]>([]);
  const [sourceArticlesTotal, setSourceArticlesTotal] = useState(0);
  const [sourceArticlesPage, setSourceArticlesPage] = useState(1);
  const [sourceArticlesFilter, setSourceArticlesFilter] = useState('');
  const [historyLoading, setHistoryLoading] = useState(false);
  const [retryingSource, setRetryingSource] = useState('');

  const [failedArticles, setFailedArticles] = useState<FailedArticle[]>([]);
  const [failedTotal, setFailedTotal] = useState(0);
  const [failedPage, setFailedPage] = useState(1);

  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [batchState, setBatchState] = useState<BatchRetryState>(emptyBatch);
  const [batchSubmitting, setBatchSubmitting] = useState(false);
  const batchTimer = useRef<ReturnType<typeof setInterval>>();

  const pollBatch = useCallback(async () => {
    try {
      const s = await api.getBatchRetryStatus();
      setBatchState(s);
      if (!s.running) { clearInterval(batchTimer.current); refreshAll(); }
    } catch { clearInterval(batchTimer.current); }
  }, []);

  const refreshAll = useCallback(() => {
    Promise.all([
      api.getFetchOverview().then(setOverview).catch(() => {}),
      api.getFetchSources(sourceFilter).then(r => setSources(r.sources)).catch(() => {}),
      api.getFetchLogs(50).then(r => setLogs(r.logs)).catch(() => {}),
      api.getFailedArticles(1, 50).then(r => { setFailedArticles(r.articles); setFailedTotal(r.total); setFailedPage(1); }).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, [sourceFilter]);

  useEffect(() => { refreshAll(); }, [refreshAll]);

  const handleExpand = async (name: string) => {
    if (expandedSource === name) { setExpandedSource(null); return; }
    setExpandedSource(name);
    setHistoryLoading(true);
    try {
      const h = await api.getFetchSourceHistory(name, 7);
      setSourceHistory(h.history);
    } catch { setSourceHistory([]); }
    finally { setHistoryLoading(false); }
  };

  const handleViewArticles = async (name: string, status?: string, page = 1) => {
    try {
      const r = await api.getFetchSourceArticles(name, { page, limit: 30, status: status || '' });
      setSourceArticles(r.articles);
      setSourceArticlesTotal(r.total);
      setSourceArticlesPage(page);
      setSourceArticlesFilter(status || '');
    } catch { /* ignore */ }
  };

  const handleRetrySource = async (name: string) => {
    setRetryingSource(name);
    try {
      await api.retryFetchSource(name);
      setTimeout(refreshAll, 3000);
    } catch { /* ignore */ }
    finally { setRetryingSource(''); }
  };

  const handleRetryArticle = async (id: number) => {
    await api.retryArticleCache(id);
    setTimeout(refreshAll, 3000);
  };

  const handleBatchRetry = async () => {
    if (selectedIds.size === 0) return;
    setBatchSubmitting(true);
    try {
      const res = await api.retryArticlesBatch(Array.from(selectedIds));
      if (res.ok) {
        setSelectedIds(new Set());
        setBatchState({ running: true, total: res.total, done: 0, failed: 0, current: '', log: [] });
        batchTimer.current = setInterval(pollBatch, 2000);
      }
    } catch { /* ignore */ }
    finally { setBatchSubmitting(false); }
  };

  const toggleSelect = (id: number) => {
    const next = new Set(selectedIds);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelectedIds(next);
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === failedArticles.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(failedArticles.map(a => a.id)));
    }
  };

  // 重试所有失败文章
  const handleRetryAll = async () => {
    if (!confirm(`确定重试所有 ${failedTotal} 篇失败文章？同源文章间隔 5-10 秒。`)) return;
    setBatchSubmitting(true);
    try {
      const res = await api.retryArticlesBatch({ retry_all: true } as any);
      if (res.ok) {
        setSelectedIds(new Set());
        setBatchState({ running: true, total: res.total, done: 0, failed: 0, current: '', log: [] });
        batchTimer.current = setInterval(pollBatch, 2000);
      }
    } catch { /* ignore */ }
    finally { setBatchSubmitting(false); }
  };

  if (loading) {
    return <Loading text="加载数据采集状态..." />;
  }

  return (
    <div style={{ padding: 24, overflow: 'auto', flex: 1 }}>
      {/* 标题栏 */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{
          fontSize: 20,
          fontWeight: 700,
          margin: 0,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}>
          <i className="fas fa-satellite-dish" style={{ color: 'var(--accent)' }} />
          数据采集
        </h2>
      </div>

      {/* ═══ 区块 1: 总览栏 ═══ */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
        gap: 14,
        marginBottom: 24,
      }}>
        <StatCard icon="fa-rss" label="RSS 源" value={`${overview.rss.healthy} 正常 / ${overview.rss.degraded + overview.rss.failing} 异常`} color="var(--accent)" />
        <StatCard icon="fa-fire" label="平台热榜" value={`${overview.hotlist.healthy} 正常`} color="var(--accent-orange)" />
        <StatCard icon="fa-database" label="缓存覆盖率" value={`${overview.cache.cached_pct}%`} color="var(--accent-tertiary)" />
        <StatCard icon="fa-file-arrow-down" label="今日新增" value={`${overview.rss.articles_today + overview.hotlist.articles_today} 篇`} color="var(--accent-green)" />
        <StatCard icon="fa-clock" label="待下载" value={`${overview.cache.pending} 篇`} color="var(--accent-orange)" />
        <StatCard icon="fa-triangle-exclamation" label="下载失败" value={`${overview.cache.failed} 篇`} color="var(--accent-red)" />
      </div>

      {/* ═══ 区块 2: 源列表 ═══ */}
      <div style={{ marginBottom: 28 }}>
        <h3 style={{
          fontSize: 15,
          fontWeight: 600,
          marginBottom: 14,
          color: 'var(--text-primary)',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}>
          <i className="fas fa-database" style={{ color: 'var(--accent)' }} />
          数据源
        </h3>

        {/* 类型筛选 */}
        <Tabs style={{ marginBottom: 14 }}>
          {['', 'rss', 'hotlist', 'bilibili'].map(t => (
            <Tab
              key={t}
              active={sourceFilter === t}
              onClick={() => setSourceFilter(t)}
            >
              {t === '' ? '全部' : typeLabels[t] || t}
            </Tab>
          ))}
        </Tabs>

        <Card flat style={{ padding: 0 }}>
          <Table>
            <thead>
              <tr>
                <th>源名称</th>
                <th>类型</th>
                <th>最近抓取</th>
                <th>状态</th>
                <th>成功率</th>
                <th>文章(缓存/总计)</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {sources.map(s => (
                <tr
                  key={s.name}
                  style={{
                    background: s.health === 'failing' ? 'rgba(239, 83, 80, 0.04)' : undefined,
                  }}
                >
                  <td>
                    <button
                      onClick={() => handleExpand(s.name)}
                      style={{
                        background: 'none',
                        border: 'none',
                        color: 'var(--text-secondary)',
                        cursor: 'pointer',
                        fontSize: 12,
                        padding: 0,
                        fontWeight: 600,
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                      }}
                    >
                      <i className={`fas ${expandedSource === s.name ? 'fa-chevron-down' : 'fa-chevron-right'}`} style={{ fontSize: 10 }} />
                      {s.name}
                    </button>
                  </td>
                  <td>{typeLabels[s.type] || s.type}</td>
                  <td>{s.last_fetch ? formatTime(s.last_fetch) : '—'}</td>
                  <td>
                    <Badge variant={healthVariant[s.health]}>
                      {s.health === 'healthy' ? '正常' : s.health === 'degraded' ? '降级' : '异常'}
                    </Badge>
                  </td>
                  <td>{(s.success_rate_5 * 100).toFixed(0)}%</td>
                  <td>{s.cached_articles}/{s.total_articles}</td>
                  <td>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <Button variant="ghost" size="xs" onClick={() => handleViewArticles(s.name)}>
                        查看
                      </Button>
                      <Button
                        variant="ghost"
                        size="xs"
                        onClick={() => handleRetrySource(s.name)}
                        loading={retryingSource === s.name}
                      >
                        重抓
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>

        {/* 展开行内容 */}
        {expandedSource && (
          <Card flat style={{ marginTop: 12, padding: 16 }}>
            {historyLoading ? (
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>加载中...</span>
            ) : (
              <div style={{ fontSize: 12 }}>
                <div style={{ marginBottom: 10, fontWeight: 600, color: 'var(--text-secondary)' }}>
                  <i className="fas fa-history" style={{ marginRight: 6 }} />
                  最近抓取历史 (7 天)
                </div>
                {sourceHistory.length === 0 ? (
                  <span style={{ color: 'var(--text-muted)' }}>暂无记录 — 该源可能尚未被系统调度抓取</span>
                ) : (
                  <div style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 6,
                    maxHeight: 140,
                    overflowY: 'auto',
                  }}>
                    {sourceHistory.map((h, i) => (
                      <div key={i} style={{
                        display: 'flex',
                        gap: 12,
                        alignItems: 'center',
                        fontSize: 11,
                        fontFamily: 'var(--font-mono)',
                        padding: '4px 8px',
                        borderRadius: 4,
                        background: 'rgba(0, 0, 0, 0.15)',
                      }}>
                        <span style={{ color: 'var(--text-muted)', minWidth: 130 }}>
                          {h.started_at ? h.started_at.replace('T', ' ').substring(0, 19) : ''}
                        </span>
                        <Badge variant={h.status === 'ok' ? 'green' : 'red'}>
                          {h.status === 'ok' ? '成功' : '失败'}
                        </Badge>
                        <span>{h.articles_fetched} 条</span>
                        <span style={{ color: 'var(--accent-green)' }}>+{h.articles_new} 新增</span>
                        <span style={{ color: 'var(--text-muted)' }}>{h.run_type === 'manual' ? '手动' : '调度'}</span>
                        {h.error_msg && <span style={{ color: 'var(--accent-red)' }}>{h.error_msg.substring(0, 60)}</span>}
                      </div>
                    ))}
                  </div>
                )}

                {/* 源文章列表 */}
                <div style={{ marginTop: 12, borderTop: '1px solid var(--border)', paddingTop: 10 }}>
                  <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
                    {['', 'pending', 'fetched', 'failed', 'translated'].map(st => (
                      <Button
                        key={st}
                        variant={sourceArticlesFilter === st ? 'green' : 'ghost'}
                        size="xs"
                        onClick={() => handleViewArticles(expandedSource, st || undefined)}
                      >
                        {st === '' ? '全部' : st === 'pending' ? '待下载' : st === 'fetched' ? '已缓存' : st === 'failed' ? '失败' : '已翻译'}
                      </Button>
                    ))}
                  </div>
                  {sourceArticles.length > 0 && (
                    <div style={{
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 4,
                      maxHeight: 200,
                      overflowY: 'auto',
                    }}>
                      {sourceArticles.map(a => (
                        <div key={a.id} style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 10,
                          fontSize: 11,
                          padding: '4px 8px',
                          borderRadius: 4,
                          transition: 'background var(--transition-fast)',
                        }}
                        onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-card-hover)')}
                        onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                        >
                          <span style={{ minWidth: 36, color: 'var(--text-muted)' }}>#{a.id}</span>
                          <a
                            href={`/articles/${a.id}`}
                            target="_blank"
                            style={{
                              flex: 1,
                              color: 'var(--text-secondary)',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                              textDecoration: 'none',
                            }}
                          >
                            {a.title}
                          </a>
                          <Badge variant={statusVariant[a.content_status] || 'orange'}>
                            {a.content_status}
                          </Badge>
                        </div>
                      ))}
                    </div>
                  )}
                  {sourceArticlesTotal > 0 && (
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>
                      共 {sourceArticlesTotal} 篇 · 显示前 30 篇
                    </div>
                  )}
                </div>
              </div>
            )}
          </Card>
        )}
      </div>

      {/* ═══ 区块 3: 失败文章列表 ═══ */}
      <div style={{ marginBottom: 28 }}>
        <h3 style={{
          fontSize: 15,
          fontWeight: 600,
          marginBottom: 14,
          color: 'var(--text-primary)',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}>
          <i className="fas fa-exclamation-triangle" style={{ color: 'var(--accent-red)' }} />
          下载失败的文章
          <Badge variant="red">{failedTotal}</Badge>
        </h3>

        {batchState.running && (
          <div style={{
            marginBottom: 12,
            padding: '10px 14px',
            background: 'rgba(0, 212, 255, 0.08)',
            borderRadius: 8,
            border: '1px solid rgba(0, 212, 255, 0.2)',
            fontSize: 12,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}>
            <i className="fas fa-spinner fa-spin" style={{ color: 'var(--accent)' }} />
            批量重试中: {batchState.done}/{batchState.total} · {batchState.current}
          </div>
        )}

        <div style={{
          marginBottom: 12,
          display: 'flex',
          gap: 10,
          alignItems: 'center',
        }}>
          <Button
            variant="ghost"
            size="xs"
            onClick={toggleSelectAll}
          >
            {selectedIds.size > 0 ? `取消全选 (${selectedIds.size})` : '全选当前页'}
          </Button>
          <Button
            variant={selectedIds.size > 0 ? 'primary' : 'ghost'}
            size="xs"
            onClick={handleBatchRetry}
            disabled={selectedIds.size === 0 || batchSubmitting || batchState.running}
            loading={batchSubmitting}
          >
            批量重试 ({selectedIds.size} 篇)
          </Button>
          <Button
            variant="orange"
            size="xs"
            icon="fa-redo"
            onClick={handleRetryAll}
            disabled={batchSubmitting || batchState.running}
            loading={batchSubmitting}
          >
            重试所有失败 ({failedTotal} 篇)
          </Button>
        </div>

        <Card flat style={{ padding: 0 }}>
          <Table>
            <thead>
              <tr>
                <th style={{ width: 32 }}>
                  <input
                    type="checkbox"
                    onChange={toggleSelectAll}
                    checked={selectedIds.size > 0 && selectedIds.size === failedArticles.length}
                    style={{ accentColor: 'var(--accent)' }}
                  />
                </th>
                <th>ID</th>
                <th>标题</th>
                <th>来源</th>
                <th>错误</th>
                <th>最近尝试</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {failedArticles.map(a => (
                <tr key={a.id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selectedIds.has(a.id)}
                      onChange={() => toggleSelect(a.id)}
                      style={{ accentColor: 'var(--accent)' }}
                    />
                  </td>
                  <td>{a.id}</td>
                  <td style={{
                    maxWidth: 260,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}>
                    {a.title}
                  </td>
                  <td>{a.source}</td>
                  <td style={{ color: 'var(--accent-red)' }}>{a.error}</td>
                  <td>{a.content_fetched_at ? formatTime(a.content_fetched_at) : '—'}</td>
                  <td>
                    <Button variant="ghost" size="xs" onClick={() => handleRetryArticle(a.id)}>
                      重试
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>

        {failedTotal > 50 && (
          <div style={{ marginTop: 10, display: 'flex', gap: 8, alignItems: 'center' }}>
            <Button
              variant="ghost"
              size="xs"
              onClick={() => { setFailedPage(failedPage - 1); api.getFailedArticles(failedPage - 1, 50).then(r => setFailedArticles(r.articles)).catch(() => {}); }}
              disabled={failedPage <= 1}
            >
              上一页
            </Button>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              第 {failedPage}/{Math.ceil(failedTotal / 50)} 页
            </span>
            <Button
              variant="ghost"
              size="xs"
              onClick={() => { setFailedPage(failedPage + 1); api.getFailedArticles(failedPage + 1, 50).then(r => setFailedArticles(r.articles)).catch(() => {}); }}
              disabled={failedPage >= Math.ceil(failedTotal / 50)}
            >
              下一页
            </Button>
          </div>
        )}
      </div>

      {/* ═══ 区块 4: 最近抓取日志 ═══ */}
      <div>
        <h3 style={{
          fontSize: 15,
          fontWeight: 600,
          marginBottom: 14,
          color: 'var(--text-primary)',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}>
          <i className="fas fa-terminal" style={{ color: 'var(--accent)' }} />
          最近抓取日志
        </h3>
        <div style={{
          background: '#0d1117',
          borderRadius: 'var(--radius-md)',
          padding: '10px 12px',
          maxHeight: 240,
          overflowY: 'auto',
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          lineHeight: 1.8,
          border: '1px solid var(--border)',
        }}>
          {logs.map((l, i) => {
            const icon = l.status === 'ok' ? '✅' : l.status === 'partial' ? '⚠️' : '❌';
            const color = l.status === 'ok' ? '#81c784' : l.status === 'partial' ? '#ffb74d' : '#ef5350';
            return (
              <div key={i} style={{ color }}>
                [{formatTime(l.started_at)}] {l.source_name} {icon} {l.articles_fetched} 条, +{l.articles_new} 新增
                {l.duration_ms > 0 ? ` · ${(l.duration_ms / 1000).toFixed(1)}s` : ''}
                {l.run_type === 'manual' ? ' [手动]' : ''}
                {l.error_msg ? ` — ${l.error_msg}` : ''}
              </div>
            );
          })}
          {logs.length === 0 && (
            <div style={{ color: 'var(--text-muted)' }}>暂无抓取记录 — 等待首次调度运行</div>
          )}
        </div>
      </div>
    </div>
  );
}

function formatTime(iso: string) {
  if (!iso) return '—';
  try {
    const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return iso.substring(0, 19).replace('T', ' ');
  }
}
