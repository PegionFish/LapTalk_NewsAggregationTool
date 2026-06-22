import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { FetchOverview, FetchSource, FetchLog, FailedArticle, FetchArticleItem, BatchRetryState, ScheduleInfo } from '../types';
import { Card, Button, Badge, Table, Tabs, Tab, StatCard, Loading } from '../components/ui';

const emptyOverview: FetchOverview = {
  rss: { total_sources: 0, healthy: 0, degraded: 0, failing: 0, last_run: null, articles_today: 0, articles_yesterday: 0 },
  hotlist: { total_sources: 0, healthy: 0, degraded: 0, failing: 0, last_run: null, articles_today: 0, articles_yesterday: 0 },
  cache: { total_articles: 0, cached: 0, pending: 0, failed: 0, cached_pct: 0 },
};

const emptyBatch: BatchRetryState = { running: false, total: 0, done: 0, failed: 0, skipped: 0, current: '', log: [] };

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

/** 计算今日新增的趋势 */
function calcTrend(today: number, yesterday: number): 'up' | 'down' | 'flat' | null {
  if (today === 0 && yesterday === 0) return null;
  if (today > yesterday) return 'up';
  if (today < yesterday) return 'down';
  return 'flat';
}

type TabKey = 'overview' | 'schedule';
const TABS: { key: TabKey; icon: string; label: string }[] = [
  { key: 'overview', icon: 'fa-database', label: '数据源' },
  { key: 'schedule', icon: 'fa-clock', label: '调度管理' },
];

export default function FetchMonitor() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<TabKey>('overview');
  const [overview, setOverview] = useState<FetchOverview>(emptyOverview);
  const [sources, setSources] = useState<FetchSource[]>([]);
  const [logs, setLogs] = useState<FetchLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState('');
  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(''), 3500); };

  const [pipelineStatus, setPipelineStatus] = useState<{ running: boolean; last_run: string | null; last_status: string | null; current_step: string | null }>({ running: false, last_run: null, last_status: null, current_step: null });
  const [quickActionLoading, setQuickActionLoading] = useState(''); // 'pipeline' | 'retry'

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

  // ── 批量重试进度计算 ──
  const batchPct = useMemo(() => {
    if (batchState.total === 0) return 0;
    return Math.round((batchState.done / batchState.total) * 100);
  }, [batchState.done, batchState.total]);

  const batchElapsed = useMemo(() => {
    const secs = batchState.elapsed_seconds ?? 0;
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  }, [batchState.elapsed_seconds]);

  const batchEta = useMemo(() => {
    if (batchState.done < 5 || !batchState.elapsed_seconds || batchState.elapsed_seconds < 2) return '';
    const rate = batchState.done / batchState.elapsed_seconds;
    if (rate <= 0) return '';
    const remaining = Math.max(0, (batchState.total - batchState.done) / rate);
    const m = Math.floor(remaining / 60);
    const s = Math.round(remaining % 60);
    return `~${m}:${s.toString().padStart(2, '0')}`;
  }, [batchState.done, batchState.total, batchState.elapsed_seconds]);

  // 调度管理状态
  const [scheduleInfo, setScheduleInfo] = useState<ScheduleInfo | null>(null);
  const [scheduleHours, setScheduleHours] = useState<number[]>([10, 17]);
  const [scheduleMinutes, setScheduleMinutes] = useState<number[]>([0, 0]);
  const [scheduleEnabled, setScheduleEnabled] = useState(true);
  const [scheduleLogs, setScheduleLogs] = useState<string[]>([]);
  const [scheduleSaving, setScheduleSaving] = useState(false);
  const [scheduleMessage, setScheduleMessage] = useState('');
  const [showAddTime, setShowAddTime] = useState(false);
  const [newHour, setNewHour] = useState(12);
  const [newMinute, setNewMinute] = useState(0);

  const failedSectionRef = useRef<HTMLDivElement>(null);

  // Pipeline 状态轮询
  useEffect(() => {
    api.getPipelineStatus().then(setPipelineStatus).catch(() => {});
    const t = setInterval(() => {
      api.getPipelineStatus().then(setPipelineStatus).catch(() => {});
    }, 8000);
    return () => clearInterval(t);
  }, []);

  // 挂载时检查是否有运行中的批量重试（跨页面导航恢复状态）
  useEffect(() => {
    api.getBatchRetryStatus().then((s: BatchRetryState) => {
      if (s.running) {
        setBatchState(s);
        batchTimer.current = setInterval(pollBatch, 2000);
      }
    }).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // 快捷操作
  const handleQuickPipeline = async () => {
    setQuickActionLoading('pipeline');
    setActiveTab('schedule');
    showToast('正在触发采集管道...');
    try {
      await api.triggerPipeline();
      setTimeout(() => {
        setQuickActionLoading('');
        api.getPipelineStatus().then(setPipelineStatus).catch(() => {});
      }, 2000);
    } catch (e) {
      showToast('触发失败: ' + (e as Error).message);
      setQuickActionLoading('');
    }
  };

  const handleQuickRetryAll = async () => {
    if (!confirm(`确定重试所有 ${failedTotal} 篇失败文章？同源文章间隔 5-10 秒。`)) return;
    setQuickActionLoading('retry');
    try {
      const res = await api.retryArticlesBatch({ retry_all: true } as any);
      if (res.ok) {
        showToast(`开始批量重试 ${res.total} 篇`);
        setBatchState({ running: true, total: res.total, done: 0, failed: 0, current: '', log: [] });
        batchTimer.current = setInterval(pollBatch, 2000);
      } else {
        showToast((res as any).message || '重试启动失败');
      }
    } catch (e) {
      showToast('重试失败: ' + (e as Error).message);
    }
    setQuickActionLoading('');
  };

  const handleNavigateToDashboard = () => {
    navigate('/');
  };

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

  const refreshSchedule = useCallback(() => {
    api.getSchedule().then(info => {
      setScheduleInfo(info);
      setScheduleEnabled(info.enabled);
      setScheduleHours(info.schedule.map(s => s.hour));
      setScheduleMinutes(info.schedule.map(s => s.minute));
    }).catch(() => {});
    api.getScheduleLogs(30).then(r => setScheduleLogs(r.logs)).catch(() => {});
  }, []);

  useEffect(() => { refreshAll(); refreshSchedule(); }, [refreshAll, refreshSchedule]);

  // 调度 Tab 激活时自动刷新日志
  const scheduleTimer = useRef<ReturnType<typeof setInterval>>();
  useEffect(() => {
    if (activeTab === 'schedule') {
      refreshSchedule();
      scheduleTimer.current = setInterval(refreshSchedule, 5000);
    } else {
      clearInterval(scheduleTimer.current);
    }
    return () => clearInterval(scheduleTimer.current);
  }, [activeTab, refreshSchedule]);

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
      } else {
        showToast((res as any).message || '重试启动失败');
      }
    } catch (e) { showToast('重试失败: ' + (e as Error).message); }
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

  const handleRetryAll = async () => {
    if (!confirm(`确定重试所有 ${failedTotal} 篇失败文章？同源文章间隔 5-10 秒。`)) return;
    setBatchSubmitting(true);
    try {
      const res = await api.retryArticlesBatch({ retry_all: true } as any);
      if (res.ok) {
        setSelectedIds(new Set());
        setBatchState({ running: true, total: res.total, done: 0, failed: 0, current: '', log: [] });
        batchTimer.current = setInterval(pollBatch, 2000);
      } else {
        showToast((res as any).message || '重试启动失败');
      }
    } catch (e) { showToast('重试失败: ' + (e as Error).message); }
    finally { setBatchSubmitting(false); }
  };

  const handleCancelBatch = async () => {
    try {
      await api.cancelBatchRetry();
      clearInterval(batchTimer.current);
      setBatchState(emptyBatch);
      showToast('重试任务已取消');
      refreshAll();
    } catch (e) { showToast('取消失败: ' + (e as Error).message); }
  };

  // ── 调度管理操作 ──
  const handleSaveSchedule = async () => {
    setScheduleSaving(true);
    setScheduleMessage('');
    try {
      await api.updateSchedule({
        enabled: scheduleEnabled,
        hours: scheduleHours,
        minutes: scheduleMinutes,
      });
      setScheduleMessage('调度配置已保存并重载');
      setTimeout(refreshSchedule, 500);
    } catch (e) {
      setScheduleMessage('保存失败: ' + (e as Error).message);
    }
    setScheduleSaving(false);
  };

  const handleToggleSchedule = async () => {
    try {
      const res = await api.toggleSchedule(!scheduleEnabled);
      setScheduleEnabled(!scheduleEnabled);
      setScheduleMessage(res.message);
      setTimeout(refreshSchedule, 500);
    } catch (e) {
      setScheduleMessage('操作失败: ' + (e as Error).message);
    }
  };

  const handleAddTimeSlot = () => {
    setScheduleHours([...scheduleHours, newHour]);
    setScheduleMinutes([...scheduleMinutes, newMinute]);
    setShowAddTime(false);
  };

  const handleRemoveTimeSlot = (index: number) => {
    if (scheduleHours.length <= 1) return;
    setScheduleHours(scheduleHours.filter((_, i) => i !== index));
    setScheduleMinutes(scheduleMinutes.filter((_, i) => i !== index));
  };

  const handleManualRun = async () => {
    try {
      await api.triggerPipeline();
      setScheduleMessage('管道已手动触发');
    } catch (e) {
      setScheduleMessage('触发失败: ' + (e as Error).message);
    }
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

      {/* Toast */}
      {toast && (
        <div style={{
          marginBottom: 16,
          padding: '10px 14px',
          background: 'rgba(0, 212, 255, 0.1)',
          border: '1px solid rgba(0, 212, 255, 0.25)',
          borderRadius: 8,
          color: 'var(--accent)',
          fontSize: 12,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          animation: 'ui-fadeIn 0.3s ease',
        }}>
          <i className="fas fa-info-circle" />
          {toast}
        </div>
      )}

      {/* ═══ 区块 1: 总览栏（可点击）═══ */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
        gap: 14,
        marginBottom: 16,
      }}>
        <StatCard icon="fa-rss" label="RSS 源"
          value={`${overview.rss.healthy} 正常 / ${overview.rss.degraded + overview.rss.failing} 异常`}
          color="var(--accent)" hint="点击筛选 RSS 源列表"
          onClick={() => { setActiveTab('overview'); setSourceFilter('rss'); }} />
        <StatCard icon="fa-fire" label="平台热榜"
          value={`${overview.hotlist.healthy} 正常`}
          color="var(--accent-orange)" hint="点击筛选平台热榜"
          onClick={() => { setActiveTab('overview'); setSourceFilter('hotlist'); }} />
        <StatCard icon="fa-database" label="缓存覆盖率"
          value={`${overview.cache.cached_pct}%`}
          color="var(--accent-tertiary)"
          hint={`${overview.cache.cached}/${overview.cache.total_articles} 篇已缓存`} />
        <StatCard icon="fa-file-arrow-down" label="今日新增"
          value={`${overview.rss.articles_today + overview.hotlist.articles_today} 篇`}
          color="var(--accent-green)"
          trend={calcTrend(overview.rss.articles_today + overview.hotlist.articles_today, overview.rss.articles_yesterday + overview.hotlist.articles_yesterday)}
          hint={`昨日: ${overview.rss.articles_yesterday + overview.hotlist.articles_yesterday} 篇`} />
        <StatCard icon="fa-clock" label="待下载"
          value={`${overview.cache.pending} 篇`}
          color="var(--accent-orange)" hint="点击触发采集管道下载"
          onClick={handleQuickPipeline} />
        <StatCard icon="fa-triangle-exclamation" label="下载失败"
          value={`${overview.cache.failed} 篇`}
          color="var(--accent-red)" hint="点击滚动到失败列表"
          onClick={() => { setActiveTab('overview'); setTimeout(() => failedSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100); }} />
      </div>

      {/* ═══ 快捷操作行 ═══ */}
      <div style={{
        marginBottom: 20,
        padding: '14px 18px',
        background: 'var(--bg-secondary)',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--border)',
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginRight: 6 }}>
          <i className="fas fa-bolt" style={{ color: 'var(--accent)', fontSize: 14 }} />
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)' }}>快捷操作</span>
        </div>
        <Button variant="primary" size="sm" icon="fa-cloud-arrow-down"
          onClick={handleQuickPipeline}
          loading={quickActionLoading === 'pipeline'}
          disabled={quickActionLoading !== ''}>
          开始批量缓存
        </Button>
        <Button variant="orange" size="sm" icon="fa-redo"
          onClick={handleQuickRetryAll}
          loading={quickActionLoading === 'retry'}
          disabled={quickActionLoading !== ''}>
          重试全部失败
        </Button>
        <Button variant="ghost" size="sm" icon="fa-robot"
          onClick={handleNavigateToDashboard}>
          AI 仪表盘
        </Button>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto', display: 'flex', gap: 14 }}>
          <span><i className="fas fa-hourglass-half" style={{ marginRight: 4, opacity: 0.6 }} />
            待缓存 <strong style={{ color: 'var(--accent-orange)' }}>{overview.cache.pending}</strong>
          </span>
          <span><i className="fas fa-times-circle" style={{ marginRight: 4, opacity: 0.6 }} />
            已失败 <strong style={{ color: 'var(--accent-red)' }}>{overview.cache.failed}</strong>
          </span>
          <span><i className="fas fa-tachometer-alt" style={{ marginRight: 4, opacity: 0.6 }} />
            管道 <strong style={{ color: pipelineStatus.running ? 'var(--accent-tertiary)' : 'var(--text-muted)' }}>
              {pipelineStatus.running ? '运行中' : '空闲'}
            </strong>
          </span>
        </div>
      </div>

      {/* ═══ Tab 切换 ═══ */}
      <Tabs style={{ marginBottom: 20 }}>
        {TABS.map(t => (
          <Tab key={t.key} active={activeTab === t.key} onClick={() => setActiveTab(t.key)}>
            <i className={`fas ${t.icon}`} style={{ marginRight: 6 }} />
            {t.label}
          </Tab>
        ))}
      </Tabs>

      {/* ═══ Tab: 数据源 ═══ */}
      {activeTab === 'overview' && (
        <>
          {/* ═══ 区块 2: 源列表 ═══ */}
          <div style={{ marginBottom: 28 }}>
            <div style={{
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
            </div>

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
            <div style={{
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
            </div>

            {batchState.running && (
              <div style={{
                marginBottom: 12,
                padding: '12px 16px',
                background: 'rgba(0, 212, 255, 0.08)',
                borderRadius: 8,
                border: '1px solid rgba(0, 212, 255, 0.2)',
                fontSize: 12,
              }}>
                {/* 行 1: 标题栏 + 取消按钮 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <i className="fas fa-spinner fa-spin" style={{ color: 'var(--accent)', fontSize: 14 }} />
                  <span style={{ fontWeight: 600, color: 'var(--accent)' }}>
                    批量重试中: {batchState.done}/{batchState.total} ({batchPct}%)
                  </span>
                  <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                    ⏱ {batchElapsed}
                  </span>
                  {batchEta && (
                    <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                      · ETA {batchEta}
                    </span>
                  )}
                  {(batchState.skipped ?? 0) > 0 && (
                    <span style={{ color: 'var(--accent-orange)', fontSize: 11 }}>
                      · 跳过 {batchState.skipped} 死链
                    </span>
                  )}
                  {batchState.failed > 0 && (
                    <span style={{ color: 'var(--accent-red)', fontSize: 11 }}>
                      · 失败 {batchState.failed}
                    </span>
                  )}
                  <Button
                    variant="ghost"
                    size="xs"
                    onClick={handleCancelBatch}
                    style={{ marginLeft: 'auto', color: 'var(--accent-red)' }}
                  >
                    <i className="fas fa-stop" style={{ marginRight: 4 }} />
                    取消
                  </Button>
                </div>

                {/* 行 2: 进度条 */}
                <div style={{ height: 6, background: 'var(--bg-primary)', borderRadius: 3, overflow: 'hidden', marginBottom: 6 }}>
                  <div style={{
                    height: '100%', borderRadius: 3, transition: 'width 0.4s ease',
                    width: `${batchPct}%`,
                    background: 'linear-gradient(90deg, var(--accent), var(--accent-tertiary))',
                  }} />
                </div>

                {/* 行 3: 当前文章 */}
                <div style={{ color: 'var(--text-secondary)', fontSize: 11, marginBottom: 4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  📄 {batchState.current || '准备中...'}
                </div>

                {/* 行 4: 最近日志 (最后 8 条) */}
                {batchState.log && batchState.log.length > 0 && (
                  <div style={{
                    maxHeight: 100, overflow: 'auto',
                    fontSize: 10, fontFamily: 'var(--font-mono)',
                    background: 'rgba(0,0,0,0.12)', borderRadius: 4, padding: '4px 8px',
                    lineHeight: 1.7,
                  }}>
                    {batchState.log.slice(-8).map((entry, i) => {
                      const isSuccess = entry.includes('✅');
                      const isError = entry.includes('❌');
                      const isSkipped = entry.includes('💀');
                      const isWarn = entry.includes('⚠️') || entry.includes('🎭');
                      const isInfo = entry.includes('📡') || entry.includes('⏳') || entry.includes('🏁') || entry.includes('🛑');
                      return (
                        <div key={i} style={{
                          color: isSuccess ? '#81c784' : isError ? '#ef5350' : isSkipped ? '#ffb74d' : isWarn ? '#ffb74d' : isInfo ? '#64b5f6' : 'var(--text-secondary)',
                        }}>
                          {entry}
                        </div>
                      );
                    })}
                  </div>
                )}
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
                {batchState.running ? `重试中 ${batchState.done}/${batchState.total}` : `批量重试 (${selectedIds.size} 篇)`}
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
            <div style={{
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
            </div>
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
        </>
      )}

      {/* ═══ Tab: 调度管理 ═══ */}
      {activeTab === 'schedule' && (
        <>
          {/* 调度状态卡片 */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: 14,
            marginBottom: 24,
          }}>
            <StatCard
              icon="fa-power-off"
              label="调度状态"
              value={scheduleInfo?.enabled ? '已启用' : '已禁用'}
              color={scheduleInfo?.enabled ? 'var(--accent-green)' : 'var(--accent-red)'}
            />
            <StatCard
              icon="fa-server"
              label="调度器进程"
              value={scheduleInfo?.scheduler_running ? '运行中' : '已停止'}
              color={scheduleInfo?.scheduler_running ? 'var(--accent-green)' : 'var(--accent-orange)'}
            />
            <StatCard
              icon="fa-calendar-check"
              label="上次运行"
              value={scheduleInfo?.last_run ? formatTime(scheduleInfo.last_run) : '—'}
              color="var(--accent)"
            />
            <StatCard
              icon="fa-check-circle"
              label="上次状态"
              value={scheduleInfo?.last_status === 'success' ? '成功' : scheduleInfo?.last_status === 'failed' ? '失败' : '—'}
              color={scheduleInfo?.last_status === 'success' ? 'var(--accent-green)' : scheduleInfo?.last_status === 'failed' ? 'var(--accent-red)' : 'var(--text-muted)'}
            />
          </div>

          {/* 定时配置 */}
          <Card flat style={{ padding: 20, marginBottom: 20 }}>
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: 20,
            }}>
              <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 8 }}>
                <i className="fas fa-clock" style={{ color: 'var(--accent)' }} />
                定时配置
              </div>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <Button
                  variant={scheduleEnabled ? 'green' : 'ghost'}
                  size="sm"
                  onClick={handleToggleSchedule}
                >
                  <i className={`fas fa-${scheduleEnabled ? 'pause' : 'play'}`} style={{ marginRight: 6 }} />
                  {scheduleEnabled ? '禁用调度' : '启用调度'}
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  icon="fa-play"
                  onClick={handleManualRun}
                >
                  立即运行
                </Button>
              </div>
            </div>

            {/* 时间列表 */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 8 }}>
                每天执行时间（24 小时制，最多 48 个）:
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginBottom: 10 }}>
                {scheduleHours.map((h, i) => (
                  <div key={i} style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                    padding: '4px 10px',
                    background: 'var(--bg-card)',
                    borderRadius: 6,
                    border: '1px solid var(--border)',
                    fontSize: 12,
                  }}>
                    <i className="fas fa-clock" style={{ color: 'var(--accent)', fontSize: 10 }} />
                    <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                      {String(h).padStart(2, '0')}:{String(scheduleMinutes[i] || 0).padStart(2, '0')}
                    </span>
                    <button
                      onClick={() => handleRemoveTimeSlot(i)}
                      disabled={scheduleHours.length <= 1}
                      style={{
                        background: 'none',
                        border: 'none',
                        color: 'var(--accent-red)',
                        cursor: scheduleHours.length <= 1 ? 'not-allowed' : 'pointer',
                        fontSize: 10,
                        padding: '0 2px',
                        opacity: scheduleHours.length <= 1 ? 0.3 : 1,
                      }}
                    >
                      <i className="fas fa-times" />
                    </button>
                  </div>
                ))}
              </div>

              {/* 快捷添加 */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginBottom: 8 }}>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>快捷:</span>
                {[
                  { label: '每2小时', gen: () => Array.from({ length: 12 }, (_, i) => ({ h: i * 2, m: 0 })) },
                  { label: '每3小时', gen: () => Array.from({ length: 8 }, (_, i) => ({ h: i * 3, m: 0 })) },
                  { label: '每4小时', gen: () => Array.from({ length: 6 }, (_, i) => ({ h: i * 4, m: 0 })) },
                  { label: '工作日 9-18 每2h', gen: () => Array.from({ length: 5 }, (_, i) => ({ h: 9 + i * 2, m: 0 })) },
                  { label: '早中晚', gen: () => [{ h: 8, m: 0 }, { h: 13, m: 0 }, { h: 20, m: 0 }] },
                ].map(preset => (
                  <button
                    key={preset.label}
                    onClick={() => {
                      const slots = preset.gen();
                      setScheduleHours(slots.map(s => s.h));
                      setScheduleMinutes(slots.map(s => s.m));
                    }}
                    style={{
                      padding: '3px 8px',
                      background: 'var(--bg-card)',
                      border: '1px solid var(--border)',
                      borderRadius: 4,
                      color: 'var(--text-secondary)',
                      cursor: 'pointer',
                      fontSize: 10,
                    }}
                  >
                    {preset.label}
                  </button>
                ))}
              </div>

              {/* 手动添加 */}
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                {showAddTime ? (
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                    padding: '4px 8px',
                    background: 'var(--bg-card)',
                    borderRadius: 6,
                    border: '1px solid var(--accent)',
                  }}>
                    <select
                      value={newHour}
                      onChange={e => setNewHour(Number(e.target.value))}
                      style={{
                        width: 50, padding: '2px 4px',
                        background: 'var(--bg-input, #1a1a2e)', color: 'var(--text-primary)',
                        border: '1px solid var(--border)', borderRadius: 4, fontSize: 12,
                      }}
                    >
                      {Array.from({ length: 24 }, (_, i) => (
                        <option key={i} value={i}>{String(i).padStart(2, '0')}</option>
                      ))}
                    </select>
                    <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>:</span>
                    <select
                      value={newMinute}
                      onChange={e => setNewMinute(Number(e.target.value))}
                      style={{
                        width: 50, padding: '2px 4px',
                        background: 'var(--bg-input, #1a1a2e)', color: 'var(--text-primary)',
                        border: '1px solid var(--border)', borderRadius: 4, fontSize: 12,
                      }}
                    >
                      {[0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55].map(m => (
                        <option key={m} value={m}>{String(m).padStart(2, '0')}</option>
                      ))}
                    </select>
                    <button
                      onClick={handleAddTimeSlot}
                      disabled={scheduleHours.length >= 48}
                      style={{
                        background: 'var(--accent)', border: 'none', color: '#000',
                        cursor: scheduleHours.length >= 48 ? 'not-allowed' : 'pointer',
                        borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 600,
                        opacity: scheduleHours.length >= 48 ? 0.5 : 1,
                      }}
                    >
                      <i className="fas fa-check" />
                    </button>
                    <button
                      onClick={() => setShowAddTime(false)}
                      style={{
                        background: 'none', border: 'none', color: 'var(--text-muted)',
                        cursor: 'pointer', padding: '2px 4px', fontSize: 11,
                      }}
                    >
                      <i className="fas fa-times" />
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setShowAddTime(true)}
                    disabled={scheduleHours.length >= 48}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 4,
                      padding: '4px 10px',
                      background: 'var(--bg-card)',
                      borderRadius: 6,
                      border: '1px dashed var(--border)',
                      color: scheduleHours.length >= 48 ? 'var(--text-muted)' : 'var(--text-secondary)',
                      cursor: scheduleHours.length >= 48 ? 'not-allowed' : 'pointer',
                      fontSize: 11,
                    }}
                  >
                    <i className="fas fa-plus" style={{ fontSize: 9 }} />
                    添加
                  </button>
                )}
                <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                  {scheduleHours.length}/48
                </span>
              </div>
            </div>

            {/* 保存按钮 */}
            <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
              <Button
                variant="primary"
                size="sm"
                icon="fa-save"
                onClick={handleSaveSchedule}
                loading={scheduleSaving}
              >
                保存配置
              </Button>
              {scheduleMessage && (
                <span style={{
                  fontSize: 12,
                  color: scheduleMessage.includes('失败') ? 'var(--accent-red)' : 'var(--accent-green)',
                }}>
                  {scheduleMessage}
                </span>
              )}
            </div>
          </Card>

          {/* 调度日志 */}
          <div>
            <div style={{
              fontSize: 15,
              fontWeight: 600,
              marginBottom: 14,
              color: 'var(--text-primary)',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}>
              <i className="fas fa-scroll" style={{ color: 'var(--accent)' }} />
              调度日志
            </div>
            <div style={{
              background: '#0d1117',
              borderRadius: 'var(--radius-md)',
              padding: '10px 12px',
              maxHeight: 300,
              overflowY: 'auto',
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              lineHeight: 1.8,
              border: '1px solid var(--border)',
            }}>
              {scheduleLogs.map((log, i) => (
                <div key={i} style={{
                  color: log.includes('失败') || log.includes('异常') || log.includes('错误')
                    ? '#ef5350'
                    : log.includes('成功') || log.includes('启动')
                      ? '#81c784'
                      : '#90a4ae',
                }}>
                  {log}
                </div>
              ))}
              {scheduleLogs.length === 0 && (
                <div style={{ color: 'var(--text-muted)' }}>暂无调度日志</div>
              )}
            </div>
          </div>
        </>
      )}

      {/* ═══ AI 处理接力 ═══ */}
      <Card flat style={{
        marginTop: 28,
        padding: '16px 20px',
        border: '1px solid rgba(129, 199, 132, 0.15)',
        background: 'linear-gradient(135deg, rgba(129, 199, 132, 0.04), rgba(0, 212, 255, 0.03))',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
          <div style={{
            width: 36, height: 36, borderRadius: '50%',
            background: 'rgba(129, 199, 132, 0.12)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexShrink: 0,
          }}>
            <i className="fas fa-arrow-right-arrow-left" style={{ color: 'var(--accent-tertiary)', fontSize: 16 }} />
          </div>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-primary)', marginBottom: 2 }}>
              采集管道接力 — 下一步
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>
              {pipelineStatus.running
                ? `采集管道运行中: ${pipelineStatus.current_step || '处理中...'}`
                : `数据采集完成后，前往仪表盘进行 AI 翻译、分析、分类、评分等全流程处理`}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {pipelineStatus.running ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--accent-tertiary)' }}>
                <i className="fas fa-spinner fa-spin" />
                管道运行中
              </div>
            ) : (
              <>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  管道: 空闲
                  {pipelineStatus.last_run && (
                    <> · 上次: {formatTime(pipelineStatus.last_run)}</>
                  )}
                  {pipelineStatus.last_status && (
                    <> · {pipelineStatus.last_status === 'success' ? '成功' : '失败'}</>
                  )}
                </span>
                <Button variant="green" size="sm" icon="fa-robot"
                  onClick={handleNavigateToDashboard}>
                  前往 AI 仪表盘
                </Button>
              </>
            )}
          </div>
        </div>
      </Card>
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
