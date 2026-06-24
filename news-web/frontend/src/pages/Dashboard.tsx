import { useEffect, useState, useRef, useCallback } from 'react';
import { api } from '../api/client';
import type { Stats } from '../types';
import DashboardCards from '../components/DashboardCards';
import { Card, CardHeader, CardBody, Button, ProgressBar, LogPanel } from '../components/ui';

type BatchState = { running: boolean; total: number; done: number; failed: number; current: string; log?: string[]; steps?: { name: string; status: string }[] };

const emptyBatch: BatchState = { running: false, total: 0, done: 0, failed: 0, current: '' };

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState('');

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(''), 3000); };

  // KCS state
  const [kcsRunning, setKcsRunning] = useState(false); const [kcsState, setKcsState] = useState<BatchState>(emptyBatch);

  // Article pipeline state
  const [articleRunning, setArticleRunning] = useState(false);
  const [articleState, setArticleState] = useState<BatchState>(emptyBatch);
  // Event pipeline state
  const [eventRunning, setEventRunning] = useState(false);
  const [eventState, setEventState] = useState<BatchState>(emptyBatch);

  // 低分清理
  const [cleanupThreshold, setCleanupThreshold] = useState('20');
  const [cleanupPreview, setCleanupPreview] = useState<number | null>(null);
  const [cleanupLoading, setCleanupLoading] = useState(false);
  const [cleanupResult, setCleanupResult] = useState<{ deleted: number } | null>(null);
  const [cleanupConfirming, setCleanupConfirming] = useState(false);

  const handlePreviewCleanup = async () => {
    const threshold = parseFloat(cleanupThreshold);
    if (isNaN(threshold) || threshold < 0 || threshold > 100) { showToast('阈值需在 0 ~ 100 之间'); return; }
    setCleanupLoading(true);
    setCleanupResult(null);
    try {
      const res = await api.previewCleanup(threshold);
      setCleanupPreview(res.count);
    } catch (e) { showToast('预览失败: ' + (e as Error).message); }
    setCleanupLoading(false);
  };

  const handleExecuteCleanup = async () => {
    const threshold = parseFloat(cleanupThreshold);
    setCleanupConfirming(false);
    setCleanupLoading(true);
    try {
      const res = await api.executeCleanup(threshold);
      setCleanupResult({ deleted: res.deleted });
      setCleanupPreview(null);
      showToast(`已清理 ${res.deleted} 篇低分文章`);
      api.getStats().then(setStats).catch(() => {});
    } catch (e) { showToast('清理失败: ' + (e as Error).message); }
    setCleanupLoading(false);
  };

  const kcsTimer = useRef<ReturnType<typeof setInterval>>();
  const articleTimer = useRef<ReturnType<typeof setInterval>>();
  const eventTimer = useRef<ReturnType<typeof setInterval>>();

  const poll = useCallback((fn: () => Promise<unknown>, setter: (v: unknown) => void, stop: () => void, timer: ReturnType<typeof useRef<ReturnType<typeof setInterval>>>) => {
    fn().then(v => { setter(v); if (!(v as BatchState).running) { stop(); clearInterval(timer.current); } }).catch(stop);
  }, []);

  useEffect(() => { api.getStats().then(setStats).catch(() => setStats(null)).finally(() => setLoading(false)); }, []);

  useEffect(() => {
    api.getArticleStatus().then((s: unknown) => {
      const st = s as BatchState;
      if (st.running) { setArticleRunning(true); articleTimer.current = setInterval(pollArticle, 2000); }
      else setArticleState(st);
    }).catch(() => {});
    api.getEventStatus().then((s: unknown) => {
      const st = s as BatchState;
      if (st.running) { setEventRunning(true); eventTimer.current = setInterval(pollEvent, 2000); }
      else setEventState(st);
    }).catch(() => {});
    api.getBatchKcsStatus().then((s: unknown) => {
      const st = s as BatchState;
      if (st.running) { setKcsRunning(true); kcsTimer.current = setInterval(pollKcs, 2000); }
      else setKcsState(st);
    }).catch(() => {});
    return () => {
      [articleTimer, eventTimer, kcsTimer].forEach(t => clearInterval(t.current));
    };
  }, []); // eslint-disable-line

  const startPoll = (starter: () => Promise<unknown>, poller: () => void, timer: ReturnType<typeof useRef<ReturnType<typeof setInterval>>>, setRunning: (v: boolean) => void) => async () => {
    setRunning(true);
    try {
      const res = await starter() as { ok?: boolean; message?: string };
      if (res && res.ok === false) {
        setRunning(false);
        showToast(res.message || '操作被拒绝');
        return;
      }
      poller();
      timer.current = setInterval(poller, 2000);
    } catch { setRunning(false); }
  };

  // Article polling
  const pollArticle = useCallback(() => poll(
    api.getArticleStatus, v => {const s=v as BatchState; setArticleState(s); if(!s.running){setArticleRunning(false);clearInterval(articleTimer.current)}},(()=>setArticleRunning(false)),articleTimer),[]);
  const handleArticleBatch = startPoll(api.startArticleBatch, pollArticle, articleTimer, setArticleRunning);

  // Event polling
  const pollEvent = useCallback(() => poll(
    api.getEventStatus, v => {const s=v as BatchState; setEventState(s); if(!s.running){setEventRunning(false);clearInterval(eventTimer.current)}},(()=>setEventRunning(false)),eventTimer),[]);
  const handleEventNightly = startPoll(api.startEventNightly, pollEvent, eventTimer, setEventRunning);
  const handleRecluster = startPoll(api.startRecluster, pollEvent, eventTimer, setEventRunning);
  const handleSummarize = startPoll(api.startSummarize, pollEvent, eventTimer, setEventRunning);
  const handleBuildChains = startPoll(api.startBuildChains, pollEvent, eventTimer, setEventRunning);

  // KCS polling
  const pollKcs = useCallback(() => poll(api.getBatchKcsStatus, v => {const s=v as BatchState; setKcsState(s); if(!s.running){setKcsRunning(false);clearInterval(kcsTimer.current)}},(()=>setKcsRunning(false)),kcsTimer),[]);
  const handleKcs = startPoll(api.startBatchKcs, pollKcs, kcsTimer, setKcsRunning);

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
          <i className="fas fa-chart-pie" style={{ color: 'var(--accent)' }} />
          仪表盘
        </h2>
      </div>

      {/* Toast 提示 */}
      {toast && (
        <div style={{
          marginBottom: 16,
          padding: '12px 16px',
          background: 'rgba(255, 193, 7, 0.12)',
          border: '1px solid rgba(255, 193, 7, 0.3)',
          borderRadius: 8,
          color: '#ffc107',
          fontSize: 13,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          animation: 'ui-fadeIn 0.3s ease',
        }}>
          <i className="fas fa-exclamation-triangle" />
          {toast}
        </div>
      )}

      {/* 统计卡片 */}
      <DashboardCards stats={stats} loading={loading} />

      {/* AI Processing Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 16, marginTop: 16 }}>
        {/* Article Processing Card */}
        <Card>
          <CardHeader icon="fa-newspaper" iconColor="var(--accent-blue)" title="📰 文章处理" desc="缓存→清洗→翻译→分析+KCS" />
          <CardBody>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <Button variant={articleRunning ? 'ghost' : 'primary'} onClick={articleRunning ? () => { api.cancelEventOp('article'); setArticleRunning(false); } : handleArticleBatch}
                      icon={articleRunning ? 'fa-stop' : 'fa-play'}>
                {articleRunning ? '停止' : '一键处理全部'}
              </Button>
            </div>
            {articleRunning && <ProgressBar done={articleState.done} total={articleState.total} color="var(--accent-blue)" />}
            {articleRunning && articleState.log && <LogPanel entries={articleState.log} />}
          </CardBody>
        </Card>

        {/* Event Pipeline Card */}
        <Card>
          <CardHeader icon="fa-link" iconColor="var(--accent)" title="🔗 事件管线" desc="聚类→摘要→逻辑链 · 凌晨1:00自动执行" />
          <CardBody>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              <Button variant={eventRunning ? 'ghost' : 'primary'} onClick={eventRunning ? () => { api.cancelEventOp('nightly'); setEventRunning(false); } : handleEventNightly}
                      icon={eventRunning ? 'fa-stop' : 'fa-play'}>
                {eventRunning ? '停止' : '启动事件管线'}
              </Button>
              <Button variant="ghost" onClick={handleRecluster} disabled={eventRunning}>重聚类</Button>
              <Button variant="ghost" onClick={handleSummarize} disabled={eventRunning}>生成摘要</Button>
              <Button variant="ghost" onClick={handleBuildChains} disabled={eventRunning}>构建逻辑链</Button>
            </div>
            {eventRunning && eventState.steps && (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
                {eventState.steps.map((s: {name: string; status: string}, i: number) => (
                  <span key={i} style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10,
                    background: s.status === 'done' ? 'rgba(129,199,132,0.12)' : s.status === 'running' ? 'rgba(0,212,255,0.12)' : 'transparent' }}>
                    {s.status === 'done' ? '✅' : s.status === 'running' ? '⏳' : '⬜'} {s.name}
                  </span>
                ))}
              </div>
            )}
            {eventRunning && eventState.log && <LogPanel entries={eventState.log} />}
          </CardBody>
        </Card>
      </div>

      {/* KCS Card */}
      <div style={{ marginTop: 16 }}>
        <Card>
          <CardHeader icon="fa-bolt" iconColor="var(--accent-tertiary)" title="AI KCS 合并处理" desc="一次调用完成关键词提取、话题分类、优先级评分" />
          <CardBody>
            <Button variant="green" onClick={handleKcs} loading={kcsRunning} icon="fa-play">
              KCS 合并处理
            </Button>
            {kcsState.total > 0 && (
              <ProgressBar done={kcsState.done} total={kcsState.total} failed={kcsState.failed} current={kcsState.current} color="var(--accent-tertiary)" />
            )}
          </CardBody>
          {kcsState.log && kcsState.log.length > 0 && <LogPanel entries={kcsState.log} />}
        </Card>
      </div>

      {/* ═══ 低分新闻手动清理 ═══ */}
      <div style={{ marginTop: 24 }}>
        <Card style={{
          background: 'linear-gradient(135deg, rgba(239, 83, 80, 0.06), rgba(255, 193, 7, 0.04))',
          border: '1px solid rgba(239, 83, 80, 0.2)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14 }}>
            <i className="fas fa-broom" style={{ color: 'var(--accent-red)', fontSize: 22 }} />
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 700, fontSize: 15 }}>低分新闻清理</div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                删除评分低于阈值且未被人工处理的文章（已审核 / 已处理的文章受保护）
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <label style={{ fontSize: 12, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 6 }}>
              评分阈值
              <input
                type="number"
                step="1"
                min="0"
                max="100"
                value={cleanupThreshold}
                onChange={e => { setCleanupThreshold(e.target.value); setCleanupPreview(null); setCleanupResult(null); }}
                style={{
                  width: 80,
                  padding: '6px 8px',
                  background: 'var(--bg-primary)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  color: 'var(--text-primary)',
                  fontSize: 12,
                  outline: 'none',
                }}
              />
            </label>

            <Button
              variant="ghost"
              size="sm"
              icon={cleanupLoading ? undefined : 'fa-eye'}
              onClick={handlePreviewCleanup}
              disabled={cleanupLoading}
              loading={cleanupLoading}
            >
              预览
            </Button>

            {cleanupPreview !== null && !cleanupConfirming && (
              <Button
                variant="ghost"
                size="sm"
                icon="fa-trash"
                onClick={() => setCleanupConfirming(true)}
                style={{ borderColor: 'var(--accent-red)', color: 'var(--accent-red)' }}
              >
                执行清理
              </Button>
            )}
          </div>

          {/* 预览结果 */}
          {cleanupPreview !== null && (
            <div style={{
              marginTop: 12, padding: '10px 14px',
              background: cleanupPreview > 0 ? 'rgba(255, 193, 7, 0.1)' : 'rgba(129, 199, 132, 0.1)',
              border: `1px solid ${cleanupPreview > 0 ? 'rgba(255, 193, 7, 0.3)' : 'rgba(129, 199, 132, 0.3)'}`,
              borderRadius: 8, fontSize: 12, color: 'var(--text-secondary)',
              display: 'flex', alignItems: 'center', gap: 8,
            }}>
              <i className={`fas ${cleanupPreview > 0 ? 'fa-exclamation-triangle' : 'fa-check-circle'}`}
                 style={{ color: cleanupPreview > 0 ? 'var(--accent-orange)' : 'var(--accent-tertiary)' }} />
              {cleanupPreview > 0
                ? `将清理 ${cleanupPreview} 篇评分低于 ${cleanupThreshold} 的文章`
                : `没有符合条件（评分 < ${cleanupThreshold}）的可清理文章`}
            </div>
          )}

          {/* 二次确认 */}
          {cleanupConfirming && (
            <div style={{
              marginTop: 12, padding: 14,
              background: 'rgba(239, 83, 80, 0.08)',
              border: '1px solid rgba(239, 83, 80, 0.3)',
              borderRadius: 8,
            }}>
              <div style={{ fontSize: 12, color: 'var(--accent-red)', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
                <i className="fas fa-exclamation-circle" />
                确认删除 {cleanupPreview} 篇文章？此操作不可撤销，将一并清除其评语、事件关联等数据。
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <Button variant="ghost" size="sm" icon="fa-check" onClick={handleExecuteCleanup}
                  style={{ borderColor: 'var(--accent-red)', color: 'var(--accent-red)' }}>
                  确认删除
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setCleanupConfirming(false)}>
                  取消
                </Button>
              </div>
            </div>
          )}

          {/* 执行结果 */}
          {cleanupResult && !cleanupConfirming && (
            <div style={{
              marginTop: 12, padding: '10px 14px',
              background: 'rgba(129, 199, 132, 0.1)',
              border: '1px solid rgba(129, 199, 132, 0.3)',
              borderRadius: 8, fontSize: 12, color: 'var(--accent-tertiary)',
              display: 'flex', alignItems: 'center', gap: 8,
            }}>
              <i className="fas fa-check-circle" />
              已成功清理 {cleanupResult.deleted} 篇低分文章
            </div>
          )}
        </Card>
      </div>

      {/* 数据分类与来源分布 */}
      {stats && (
        <div style={{
          marginTop: 24,
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))',
          gap: 16,
        }}>
          {/* 分类概览 */}
          <Card>
            <h3 style={{ fontSize: 14, marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
              <i className="fas fa-folder-tree" style={{ color: 'var(--accent)' }} />
              数据分类
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {Object.entries(stats.by_category).map(([cat, count]) => (
                <div key={cat} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12 }}>
                  <span style={{
                    width: 100,
                    color: 'var(--text-secondary)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}>
                    {cat}
                  </span>
                  <div style={{
                    flex: 1,
                    background: 'var(--bg-primary)',
                    borderRadius: 4,
                    height: 16,
                    overflow: 'hidden',
                  }}>
                    <div style={{
                      width: `${Math.min((count / stats.articles) * 100, 100)}%`,
                      height: '100%',
                      background: 'var(--accent-tertiary)',
                      borderRadius: 4,
                      minWidth: 3,
                    }} />
                  </div>
                  <span style={{ width: 36, textAlign: 'right', fontSize: 11, fontWeight: 600 }}>{count}</span>
                </div>
              ))}
            </div>
          </Card>

          {/* 来源分布 */}
          <Card>
            <h3 style={{ fontSize: 14, marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
              <i className="fas fa-newspaper" style={{ color: 'var(--accent-orange)' }} />
              媒体来源 TOP15
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {Object.entries(stats.by_source || {})
                .sort((a, b) => b[1] - a[1])
                .slice(0, 15)
                .map(([source, count]) => (
                  <div key={source} style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    fontSize: 12,
                    padding: '2px 0',
                  }}>
                    <span style={{
                      width: 110,
                      color: 'var(--text-secondary)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }} title={source}>
                      {source}
                    </span>
                    <div style={{
                      flex: 1,
                      background: 'var(--bg-primary)',
                      borderRadius: 4,
                      height: 14,
                      overflow: 'hidden',
                    }}>
                      <div style={{
                        width: `${Math.min((count / stats.articles) * 100, 100)}%`,
                        height: '100%',
                        background: 'var(--accent)',
                        borderRadius: 4,
                        minWidth: 3,
                      }} />
                    </div>
                    <span style={{ width: 36, textAlign: 'right', fontSize: 11, fontWeight: 600 }}>{count}</span>
                  </div>
              ))}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
