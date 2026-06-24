import { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import type { Stats } from '../types';
import DashboardCards from '../components/DashboardCards';
import { Card, CardHeader, CardBody, Button, ProgressBar, LogPanel } from '../components/ui';

type BatchState = { running: boolean; total: number; done: number; failed: number; current: string; log?: string[]; steps?: { name: string; status: string; done?: number; total?: number; current?: string }[] };

const emptyBatch: BatchState = { running: false, total: 0, done: 0, failed: 0, current: '' };

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState('');
  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(''), 3000); };

  // Article pipeline state
  const [articleRunning, setArticleRunning] = useState(false);
  const [articleState, setArticleState] = useState<BatchState>(emptyBatch);
  const [recentDone, setRecentDone] = useState<Array<{id:number,title:string,steps:Record<string,unknown>}>>([]);
  const [recentFailed, setRecentFailed] = useState<Array<{id:number,title:string,error:string}>>([]);
  const [batchETA, setBatchETA] = useState('');

  // Event pipeline state
  const [eventRunning, setEventRunning] = useState(false);
  const [eventState, setEventState] = useState<BatchState>(emptyBatch);

  // Low-score cleanup
  const [cleanupThreshold, setCleanupThreshold] = useState('20');
  const [cleanupPreview, setCleanupPreview] = useState<number | null>(null);
  const [cleanupLoading, setCleanupLoading] = useState(false);
  const [cleanupResult, setCleanupResult] = useState<{ deleted: number } | null>(null);
  const [cleanupConfirming, setCleanupConfirming] = useState(false);

  // ── SSE Connection ──
  useEffect(() => {
    const es = new EventSource('/api/dashboard/stream');

    es.addEventListener('stats', (e) => {
      const d = JSON.parse(e.data);
      setStats({ articles: d.articles, events: d.events, active_events: d.events, human_verified: 0, cache_cached: d.cached, cache_text: 0, cache_translated: 0, cache_failed: d.failed, cache_pending: d.pending, by_category: {}, by_source: {} });
    });

    es.addEventListener('article_state', (e) => {
      const d = JSON.parse(e.data);
      setArticleRunning(true);
      setArticleState({ running: true, total: d.total, done: d.done, failed: d.failed, current: d.current || '' });
    });

    es.addEventListener('event_state', (e) => {
      const d = JSON.parse(e.data);
      setEventRunning(true);
      setEventState({ running: true, total: d.steps?.length || 0, done: 0, failed: 0, current: '', steps: d.steps || [] });
    });

    es.addEventListener('article_batch_start', (e) => {
      const d = JSON.parse(e.data);
      setArticleRunning(true);
      setArticleState({ running: true, total: d.total, done: 0, failed: 0, current: '启动中...' });
      setRecentDone([]); setRecentFailed([]); setBatchETA('');
    });

    es.addEventListener('article_progress', (e) => {
      const d = JSON.parse(e.data);
      setArticleState(prev => ({ ...prev, current: `${d.title || ''} — ${d.step}`, done: d.done || prev.done, total: d.total || prev.total }));
      if (d.total && d.done) setBatchETA(`~${Math.round((d.total - d.done) * 4 / 60)}min`);
    });

    es.addEventListener('article_done', (e) => {
      const d = JSON.parse(e.data);
      setArticleState(prev => ({ ...prev, done: (prev.done || 0) + 1 }));
      setRecentDone(prev => [{ id: d.id, title: d.title || '', steps: d.steps || {} }, ...prev].slice(0, 5));
    });

    es.addEventListener('article_failed', (e) => {
      const d = JSON.parse(e.data);
      setArticleState(prev => ({ ...prev, failed: (prev.failed || 0) + 1 }));
      setRecentFailed(prev => [{ id: d.id, title: d.title || '', error: d.error || '' }, ...prev].slice(0, 10));
      // 关键错误立即告警
      if (d.error && /balance|insufficient|403|30001|额度|余额/i.test(d.error)) {
        showToast(`⚠️ API 账户余额不足！处理已中断: ${d.error}`);
      }
    });

    es.addEventListener('article_batch_done', (e) => {
      const d = JSON.parse(e.data);
      setArticleRunning(false);
      setArticleState(prev => ({ ...prev, running: false, done: d.done, failed: d.failed, current: '完成' }));
      setBatchETA('');
      showToast(`文章处理完成: ${d.done} 成功, ${d.failed} 失败`);
    });

    es.addEventListener('event_step', (e) => {
      const d = JSON.parse(e.data);
      setEventRunning(true);
      setEventState(prev => {
        const steps = [...(prev.steps || [])];
        const idx = steps.findIndex((s: {name:string}) => s.name === d.step);
        if (idx >= 0) {
          steps[idx] = { ...steps[idx], status: d.status, done: d.done, total: d.total, current: d.current };
        }
        return { ...prev, steps, running: true };
      });
    });

    es.addEventListener('event_done', (e) => {
      const d = JSON.parse(e.data);
      setEventRunning(false);
      setEventState({ running: false, total: 0, done: 0, failed: 0, current: '完成', steps: d.steps });
    });

    es.onerror = () => {}; // browser auto-reconnects

    return () => es.close();
  }, []);

  // Stats fallback
  useEffect(() => { api.getStats().then(setStats).catch(() => setStats(null)).finally(() => setLoading(false)); }, []);

  // ── Handlers ──
  const handleArticleBatch = async () => {
    try {
      const r = await api.startArticleBatch() as { ok?: boolean; message?: string };
      if (r && r.ok === false) showToast(r.message || '操作被拒绝');
    } catch (e) { showToast('启动失败'); }
  };

  const handleEventNightly = async () => {
    try {
      const r = await api.startEventNightly() as { ok?: boolean; message?: string };
      if (r && r.ok === false) showToast(r.message || '操作被拒绝');
    } catch (e) { showToast('启动失败'); }
  };

  const handleRecluster = async () => {
    try { await api.startRecluster(); } catch (e) { showToast('启动失败'); }
  };
  const handleSummarize = async () => {
    try { await api.startSummarize(); } catch (e) { showToast('启动失败'); }
  };
  const handleBuildChains = async () => {
    try { await api.startBuildChains(); } catch (e) { showToast('启动失败'); }
  };

  // ── Cleanup handlers ──
  const handlePreviewCleanup = async () => {
    const threshold = parseFloat(cleanupThreshold);
    if (isNaN(threshold) || threshold < 0 || threshold > 100) { showToast('阈值需在 0 ~ 100 之间'); return; }
    setCleanupLoading(true); setCleanupResult(null);
    try { const res = await api.previewCleanup(threshold); setCleanupPreview(res.count); } catch (e) { showToast('预览失败'); }
    setCleanupLoading(false);
  };

  const handleExecuteCleanup = async () => {
    const threshold = parseFloat(cleanupThreshold);
    setCleanupConfirming(false); setCleanupLoading(true);
    try {
      const res = await api.executeCleanup(threshold);
      setCleanupResult({ deleted: res.deleted }); setCleanupPreview(null);
      showToast(`已清理 ${res.deleted} 篇低分文章`);
    } catch (e) { showToast('清理失败'); }
    setCleanupLoading(false);
  };

  // ── Render ──
  return (
    <div style={{ padding: 24, overflow: 'auto', flex: 1 }}>
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontSize: 20, fontWeight: 700, margin: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
          <i className="fas fa-chart-pie" style={{ color: 'var(--accent)' }} /> 仪表盘
        </h2>
      </div>

      {toast && (
        <div style={{ marginBottom: 16, padding: '12px 16px', background: 'rgba(255,193,7,0.12)', border: '1px solid rgba(255,193,7,0.3)', borderRadius: 8, color: '#ffc107', fontSize: 13, display: 'flex', alignItems: 'center', gap: 10 }}>
          <i className="fas fa-exclamation-triangle" /> {toast}
        </div>
      )}

      <DashboardCards stats={stats} loading={loading} />

      {/* Pipeline Cards — 运行时全宽展开 */}
      <div style={{ display: 'grid', gridTemplateColumns: (articleRunning || eventRunning) ? '1fr' : 'repeat(auto-fit, minmax(400px, 1fr))', gap: 16, marginTop: 16 }}>

        {/* Article Processing Card */}
        <Card style={articleRunning ? { borderColor: 'var(--accent-blue)', borderWidth: 2 } : undefined}>
          <CardHeader icon="fa-newspaper" iconColor="var(--accent-blue)" title="📰 文章处理" desc={articleRunning ? `${articleState.done}/${articleState.total} 已完成 · ${articleState.failed} 失败` : '缓存→清洗→翻译→分析+KCS'} />
          <CardBody>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
              <Button variant={articleRunning ? 'ghost' : 'primary'} onClick={handleArticleBatch}
                      icon={articleRunning ? 'fa-spinner fa-spin' : 'fa-play'} disabled={articleRunning}>
                {articleRunning ? `处理中 ${articleState.done}/${articleState.total}` : '一键处理全部'}
              </Button>
              {articleRunning && batchETA && <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>ETA: {batchETA}</span>}
            </div>

            {articleRunning && (
              <div style={{ marginBottom: 12 }}>
                <ProgressBar done={articleState.done} total={articleState.total} color="var(--accent-blue)" />
                <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>
                  {articleState.current}
                </div>
              </div>
            )}

            {recentDone.length > 0 && (
              <div style={{ marginTop: 12, maxHeight: articleRunning ? 200 : 120, overflow: 'auto' }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 4 }}>最近完成 ({recentDone.length}):</div>
                {recentDone.map((item, i) => (
                  <div key={i} style={{ fontSize: 11, color: 'var(--accent-green)', padding: '2px 0', fontFamily: 'monospace' }}>
                    ✅ #{item.id} {item.title?.slice(0, 80)} — {JSON.stringify(item.steps).slice(0, 80)}
                  </div>
                ))}
              </div>
            )}

            {recentFailed.length > 0 && (
              <div style={{ marginTop: 8, maxHeight: articleRunning ? 200 : 100, overflow: 'auto' }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent-red)', marginBottom: 4 }}>失败 ({recentFailed.length}):</div>
                {recentFailed.map((item, i) => (
                  <div key={i} style={{ fontSize: 11, color: 'var(--accent-red)', padding: '2px 0', fontFamily: 'monospace' }}>
                    ❌ #{item.id} {item.title?.slice(0, 80)} — {item.error}
                  </div>
                ))}
              </div>
            )}

            <div style={{ marginTop: 12, fontSize: 10, color: 'var(--text-muted)' }}>
              📋 审计日志: logs/dashboard_audit.log
            </div>
          </CardBody>
        </Card>

        {/* Event Pipeline Card */}
        <Card style={eventRunning ? { borderColor: 'var(--accent)', borderWidth: 2 } : undefined}>
          <CardHeader icon="fa-link" iconColor="var(--accent)" title="🔗 事件管线" desc={eventRunning ? '聚类→摘要→逻辑链 进行中' : '聚类→摘要→逻辑链 · 凌晨1:00自动执行'} />
          <CardBody>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12 }}>
              <Button variant={eventRunning ? 'ghost' : 'primary'} onClick={handleEventNightly}
                      icon={eventRunning ? 'fa-spinner fa-spin' : 'fa-play'} disabled={eventRunning}>
                {eventRunning ? '运行中...' : '启动事件管线'}
              </Button>
              <Button variant="ghost" onClick={handleRecluster} disabled={eventRunning}>重聚类</Button>
              <Button variant="ghost" onClick={handleSummarize} disabled={eventRunning}>生成摘要</Button>
              <Button variant="ghost" onClick={handleBuildChains} disabled={eventRunning}>构建逻辑链</Button>
            </div>

            {eventState.steps && eventState.steps.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {eventState.steps.map((s: {name:string;status:string;done?:number;total?:number;current?:string}, i:number) => {
                  const isRunning = s.status === 'running';
                  const hasProgress = isRunning && s.total && s.total > 0;
                  return (
                    <div key={i} style={{
                      display: 'flex', flexDirection: 'column', gap: 4, padding: '8px 12px', borderRadius: 8, fontSize: 12,
                      background: s.status === 'done' ? 'rgba(129,199,132,0.08)' : isRunning ? 'rgba(0,212,255,0.08)' : 'transparent',
                      border: s.status === 'done' ? '1px solid rgba(129,199,132,0.2)' : isRunning ? '1px solid rgba(0,212,255,0.25)' : '1px solid var(--border)',
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span>{s.status === 'done' ? '✅' : isRunning ? '⏳' : '⬜'}</span>
                        <span style={{ fontWeight: 600, color: isRunning ? 'var(--accent)' : 'var(--text-primary)' }}>{s.name}</span>
                        {hasProgress && <span style={{ color: 'var(--text-secondary)', fontSize: 11 }}>{s.done}/{s.total}</span>}
                      </div>
                      {hasProgress && (
                        <div style={{ marginLeft: 24 }}>
                          <div style={{ height: 3, borderRadius: 2, background: 'var(--border)', overflow: 'hidden' }}>
                            <div style={{ height: '100%', width: `${Math.round((s.done! / s.total!) * 100)}%`, background: 'var(--accent)', borderRadius: 2, transition: 'width 1s ease' }} />
                          </div>
                          {s.current && <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 2 }}>{s.current}</div>}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      {/* Low-score Cleanup */}
      <div style={{ marginTop: 24 }}>
        <Card style={{ background: 'linear-gradient(135deg, rgba(239,83,80,0.06), rgba(255,193,7,0.04))', border: '1px solid rgba(239,83,80,0.2)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14 }}>
            <i className="fas fa-broom" style={{ color: 'var(--accent-red)', fontSize: 22 }} />
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 700, fontSize: 15 }}>低分新闻清理</div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>清理低于阈值的 AI 筛选文章</div>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input type="number" value={cleanupThreshold} onChange={e => setCleanupThreshold(e.target.value)}
                   min={0} max={100} style={{ width: 80, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: 13 }} />
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>分以下</span>
            <Button variant="ghost" onClick={handlePreviewCleanup} disabled={cleanupLoading} icon="fa-eye">预览</Button>
            {cleanupPreview !== null && (
              <>
                <span style={{ fontSize: 13, color: 'var(--accent-orange)' }}>{cleanupPreview} 篇将被清理</span>
                {!cleanupConfirming ? (
                  <Button variant="ghost" onClick={() => setCleanupConfirming(true)} icon="fa-trash" style={{ color: 'var(--accent-red)', borderColor: 'var(--accent-red)' }}>确认执行</Button>
                ) : (
                  <Button variant="ghost" onClick={handleExecuteCleanup} disabled={cleanupLoading} icon="fa-check" style={{ color: 'var(--accent-red)', borderColor: 'var(--accent-red)' }}>再次确认</Button>
                )}
              </>
            )}
          </div>
          {cleanupResult && <div style={{ marginTop: 12, fontSize: 13, color: 'var(--accent-green)' }}>✅ 已清理 {cleanupResult.deleted} 篇</div>}
        </Card>
      </div>
    </div>
  );
}
