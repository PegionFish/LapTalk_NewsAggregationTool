import { useEffect, useState, useRef, useCallback } from 'react';
import { api } from '../api/client';
import type { Stats } from '../types';
import DashboardCards from '../components/DashboardCards';
import { Card, CardHeader, CardBody, Button, ProgressBar, LogPanel } from '../components/ui';

type BatchState = { running: boolean; total: number; done: number; failed: number; current: string; log?: string[]; steps?: { name: string; status: string }[] };
type ChainState = { running: boolean; total_groups: number; chains_created: number; current: string; log?: string[] };

const emptyBatch: BatchState = { running: false, total: 0, done: 0, failed: 0, current: '' };
const emptyChain: ChainState = { running: false, total_groups: 0, chains_created: 0, current: '' };

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState('');

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(''), 3000); };
  const [translating, setTranslating] = useState(false);
  const [transState, setTransState] = useState<BatchState>(emptyBatch);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyState, setAnalyState] = useState<BatchState>(emptyBatch);
  const [chaining, setChaining] = useState(false);
  const [chainState, setChainState] = useState<ChainState>(emptyChain);
  const [kwRunning, setKwRunning] = useState(false); const [kwState, setKwState] = useState<BatchState>(emptyBatch);
  const [clsRunning, setClsRunning] = useState(false); const [clsState, setClsState] = useState<BatchState>(emptyBatch);
  const [scoreRunning, setScoreRunning] = useState(false); const [scoreState, setScoreState] = useState<BatchState>(emptyBatch);
  const [reclRunning, setReclRunning] = useState(false); const [reclState, setReclState] = useState<BatchState>(emptyBatch);
  const [esRunning, setEsRunning] = useState(false); const [esState, setEsState] = useState<BatchState>(emptyBatch);
  const [fullRunning, setFullRunning] = useState(false);
  const [fullState, setFullState] = useState<BatchState>(emptyBatch);
  const [filterRunning, setFilterRunning] = useState(false); const [filterState, setFilterState] = useState<BatchState>(emptyBatch);
  const [cleanRunning, setCleanRunning] = useState(false); const [cleanState, setCleanState] = useState<BatchState>(emptyBatch);

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

  const transTimer = useRef<ReturnType<typeof setInterval>>();
  const analyTimer  = useRef<ReturnType<typeof setInterval>>();
  const chainTimer  = useRef<ReturnType<typeof setInterval>>();
  const kwTimer = useRef<ReturnType<typeof setInterval>>();
  const clsTimer = useRef<ReturnType<typeof setInterval>>();
  const scoreTimer = useRef<ReturnType<typeof setInterval>>();
  const reclTimer = useRef<ReturnType<typeof setInterval>>();
  const esTimer = useRef<ReturnType<typeof setInterval>>();
  const fullTimer = useRef<ReturnType<typeof setInterval>>();
  const filterTimer = useRef<ReturnType<typeof setInterval>>();
  const cleanTimer = useRef<ReturnType<typeof setInterval>>();

  const poll = useCallback((fn: () => Promise<unknown>, setter: (v: unknown) => void, stop: () => void, timer: ReturnType<typeof useRef<ReturnType<typeof setInterval>>>) => {
    fn().then(v => { setter(v); if (!(v as BatchState).running) { stop(); clearInterval(timer.current); } }).catch(stop);
  }, []);

  const pollTranslate = useCallback(() => poll(
    api.getBatchTranslateStatus, v => setTransState(v as BatchState), () => setTranslating(false), transTimer), []);
  const pollAnalyze = useCallback(() => poll(
    api.getBatchAnalyzeStatus, v => setAnalyState(v as BatchState), () => setAnalyzing(false), analyTimer), []);
  const pollClean = useCallback(() => poll(
    api.getBatchCleanStatus, v => setCleanState(v as BatchState), () => setCleanRunning(false), cleanTimer), []);
  const pollChains = useCallback(() => poll(
    api.getBuildChainsStatus, v => setChainState(v as ChainState), () => setChaining(false), chainTimer), []);
  const pollFilter = useCallback(() => poll(
    api.getBatchAiFilterStatus, v => setFilterState(v as BatchState), () => setFilterRunning(false), filterTimer), []);

  useEffect(() => { api.getStats().then(setStats).catch(() => setStats(null)).finally(() => setLoading(false)); }, []);

  useEffect(() => {
    api.getBatchTranslateStatus().then((s: unknown) => { const st = s as BatchState; if (st.running) { setTranslating(true); transTimer.current = setInterval(pollTranslate, 2000); } else setTransState(st); }).catch(() => {});
    api.getBatchAnalyzeStatus().then((s: unknown)  => { const st = s as BatchState; if (st.running) { setAnalyzing(true);  analyTimer.current  = setInterval(pollAnalyze, 2000);  } else setAnalyState(st);  }).catch(() => {});
    api.getBuildChainsStatus().then((s: unknown)    => { const st = s as ChainState; if (st.running) { setChaining(true);  chainTimer.current  = setInterval(pollChains, 2000);  } else setChainState(st);  }).catch(() => {});
    api.getBatchKeywordsStatus().then((s: unknown)  => { const st = s as BatchState; if (st.running) { setKwRunning(true); kwTimer.current = setInterval(pollKw, 2000); } else setKwState(st); }).catch(() => {});
    api.getBatchClassifyStatus().then((s: unknown)  => { const st = s as BatchState; if (st.running) { setClsRunning(true); clsTimer.current = setInterval(pollCls, 2000); } else setClsState(st); }).catch(() => {});
    api.getBatchScoreStatus().then((s: unknown)     => { const st = s as BatchState; if (st.running) { setScoreRunning(true); scoreTimer.current = setInterval(pollSc, 2000); } else setScoreState(st); }).catch(() => {});
    api.getBatchReclusterStatus().then((s: unknown) => { const st = s as BatchState; if (st.running) { setReclRunning(true); reclTimer.current = setInterval(pollRecl, 2000); } else setReclState(st); }).catch(() => {});
    api.getBatchSummarizeEventsStatus().then((s: unknown) => { const st = s as BatchState; if (st.running) { setEsRunning(true); esTimer.current = setInterval(pollEs, 2000); } else setEsState(st); }).catch(() => {});
    api.getBatchAiFullStatus().then((s: unknown)    => { const st = s as BatchState; if (st.running) { setFullRunning(true); fullTimer.current = setInterval(pollFull, 2000); } else setFullState(st); }).catch(() => {});
    api.getBatchAiFilterStatus().then((s: unknown) => { const st = s as BatchState; if (st.running) { setFilterRunning(true); filterTimer.current = setInterval(pollFilter, 2000); } else setFilterState(st); }).catch(() => {});
    api.getBatchCleanStatus().then((s: unknown)   => { const st = s as BatchState; if (st.running) { setCleanRunning(true);  cleanTimer.current  = setInterval(pollClean, 2000);  } else setCleanState(st);  }).catch(() => {});
    return () => {
      [transTimer, analyTimer, chainTimer, kwTimer, clsTimer, scoreTimer, reclTimer, esTimer, fullTimer, filterTimer, cleanTimer].forEach(t => clearInterval(t.current));
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

  const handleTranslate = startPoll(api.startBatchTranslate, pollTranslate, transTimer, setTranslating);
  const handleAnalyze   = startPoll(api.startBatchAnalyze, pollAnalyze, analyTimer, setAnalyzing);
  const handleBuildChains = startPoll(api.startBuildChains, pollChains, chainTimer, setChaining);

  const pollKw = useCallback(() => poll(api.getBatchKeywordsStatus, v => {const s=v as BatchState; setKwState(s); if(!s.running){setKwRunning(false);clearInterval(kwTimer.current)}},(()=>setKwRunning(false)),kwTimer),[]);
  const handleKeywords = startPoll(api.startBatchKeywords, pollKw, kwTimer, setKwRunning);
  const pollCls = useCallback(() => poll(api.getBatchClassifyStatus, v => {const s=v as BatchState; setClsState(s); if(!s.running){setClsRunning(false);clearInterval(clsTimer.current)}},(()=>setClsRunning(false)),clsTimer),[]);
  const handleClassify = startPoll(api.startBatchClassify, pollCls, clsTimer, setClsRunning);
  const pollSc = useCallback(() => poll(api.getBatchScoreStatus, v => {const s=v as BatchState; setScoreState(s); if(!s.running){setScoreRunning(false);clearInterval(scoreTimer.current)}},(()=>setScoreRunning(false)),scoreTimer),[]);
  const handleScore = startPoll(api.startBatchScore, pollSc, scoreTimer, setScoreRunning);
  const pollRecl = useCallback(() => poll(api.getBatchReclusterStatus, v => {const s=v as BatchState; setReclState(s); if(!s.running){setReclRunning(false);clearInterval(reclTimer.current)}},(()=>setReclRunning(false)),reclTimer),[]);
  const handleRecluster = startPoll(api.startBatchRecluster, pollRecl, reclTimer, setReclRunning);
  const pollEs = useCallback(() => poll(api.getBatchSummarizeEventsStatus, v => {const s=v as BatchState; setEsState(s); if(!s.running){setEsRunning(false);clearInterval(esTimer.current)}},(()=>setEsRunning(false)),esTimer),[]);
  const handleSummarizeEvents = startPoll(api.startBatchSummarizeEvents, pollEs, esTimer, setEsRunning);

  const pollFull = useCallback(() => poll(api.getBatchAiFullStatus, v => {const s=v as BatchState; setFullState(s); if(!s.running){setFullRunning(false);clearInterval(fullTimer.current)}},(()=>setFullRunning(false)),fullTimer),[]);
  const handleFullAi = startPoll(api.startBatchAiFull, pollFull, fullTimer, setFullRunning);

  const handleFilter = startPoll(api.startBatchAiFilter, pollFilter, filterTimer, setFilterRunning);
  const handleClean  = startPoll(api.startBatchClean, pollClean, cleanTimer, setCleanRunning);

  const progressPct = (done: number, total: number) => total > 0 ? Math.round((done / total) * 100) : 0;

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

      {/* ═══ AI 批量处理 ═══ */}
      <div style={{
        marginTop: 24,
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
        gap: 16,
      }}>
        {/* ═══ 一键全流程 ═══ */}
        <Card style={{
          gridColumn: '1 / -1',
          background: 'linear-gradient(135deg, rgba(0, 212, 255, 0.08), rgba(129, 199, 132, 0.05))',
          border: '1px solid rgba(0, 212, 255, 0.2)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14 }}>
            <i className="fas fa-rocket" style={{ color: 'var(--accent)', fontSize: 24 }} />
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 700, fontSize: 15 }}>一键全流程 AI 处理</div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                翻译 → 分析 → 关键词 → 分类 → 评分 → 聚类 → 摘要 → 构筑逻辑链
              </div>
            </div>
            <Button
              variant={fullRunning ? 'ghost' : 'primary'}
              onClick={handleFullAi}
              loading={fullRunning}
              icon={fullRunning ? undefined : 'fa-play'}
            >
              {fullRunning ? '运行中...' : '启动全流程'}
            </Button>
          </div>

          {(fullRunning || fullState.total > 0) && (
            <div style={{ maxWidth: '100%' }}>
              <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginBottom: 6 }}>
                {fullRunning ? (
                  <i className="fas fa-spinner fa-spin" style={{ marginRight: 6 }} />
                ) : (
                  <i className="fas fa-check-circle" style={{ color: 'var(--accent-tertiary)', marginRight: 6 }} />
                )}
                步骤 {fullState.done}/{fullState.total || 8} · {fullState.current || '等待中...'}
              </div>

              {fullState.total > 0 && (
                <ProgressBar
                  done={fullState.done}
                  total={fullState.total}
                  color="var(--accent)"
                />
              )}

              {/* 分步状态指示器 */}
              {fullState.steps && fullState.steps.length > 0 && (
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
                  {fullState.steps.map((s, i) => {
                    const variant = s.status === 'done' ? 'green' : s.status === 'failed' ? 'red' : s.status === 'running' ? 'blue' : 'muted';
                    return (
                      <div
                        key={i}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 6,
                          padding: '4px 10px',
                          borderRadius: 14,
                          background: variant === 'green' ? 'rgba(129, 199, 132, 0.12)' : variant === 'red' ? 'rgba(239, 83, 80, 0.12)' : variant === 'blue' ? 'rgba(0, 212, 255, 0.12)' : 'transparent',
                          border: variant === 'green' ? '1px solid rgba(129, 199, 132, 0.3)' : variant === 'red' ? '1px solid rgba(239, 83, 80, 0.3)' : variant === 'blue' ? '1px solid rgba(0, 212, 255, 0.4)' : '1px solid var(--border)',
                          fontSize: 11,
                        }}
                      >
                        <span>{s.status === 'done' ? '✅' : s.status === 'failed' ? '❌' : s.status === 'running' ? '⏳' : '⬜'}</span>
                        <span style={{
                          color: s.status === 'running' ? 'var(--accent)' : 'var(--text-secondary)',
                        }}>
                          {s.name}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {fullState.log && fullState.log.length > 0 && <LogPanel entries={fullState.log} />}
        </Card>

        {/* ═══ AI 预筛选 ═══ */}
        <Card>
          <CardHeader icon="fa-filter" iconColor="var(--accent-orange)" title="AI 预筛选" desc="批量判断文章标题是否值得缓存，筛掉不需要的内容" />
          <CardBody>
            <Button
              variant="ghost"
              onClick={handleFilter}
              loading={filterRunning}
              icon="fa-play"
              style={{ borderColor: 'var(--accent-orange)', color: 'var(--accent-orange)' }}
            >
              {filterRunning ? '筛选中...' : '开始 AI 筛选'}
            </Button>
            {filterState.total > 0 && (
              <ProgressBar
                done={filterState.done}
                total={filterState.total}
                failed={filterState.failed}
                current={filterState.current}
                color="var(--accent-orange)"
              />
            )}
          </CardBody>
          {filterState.log && filterState.log.length > 0 && <LogPanel entries={filterState.log} />}
        </Card>

        {/* ═══ AI 内容清洗 ═══ */}
        <Card>
          <CardHeader icon="fa-magic" iconColor="var(--accent-blue)" title="AI 内容清洗" desc="LLM 提取纯净文章正文，去广告/导航/侧栏/弹窗" />
          <CardBody>
            <Button
              variant="ghost"
              onClick={handleClean}
              loading={cleanRunning}
              icon="fa-play"
              style={{ borderColor: 'var(--accent-blue)', color: 'var(--accent-blue)' }}
            >
              {cleanRunning ? '清洗中...' : '批量清洗所有已缓存文章'}
            </Button>
            {cleanState.total > 0 && (
              <ProgressBar
                done={cleanState.done}
                total={cleanState.total}
                failed={cleanState.failed}
                current={cleanState.current}
                color="var(--accent-blue)"
              />
            )}
          </CardBody>
          {cleanState.log && cleanState.log.length > 0 && <LogPanel entries={cleanState.log} />}
        </Card>

        {/* ═══ 批量翻译 ═══ */}
        <Card>
          <CardHeader icon="fa-language" iconColor="var(--accent-tertiary)" title="AI 批量翻译" desc="遍历英文文章 HTML，调用 API 翻译为中文" />
          <CardBody>
            <Button
              variant="green"
              onClick={handleTranslate}
              loading={translating}
              icon="fa-play"
            >
              开始批量翻译
            </Button>
            {transState.total > 0 && (
              <ProgressBar
                done={transState.done}
                total={transState.total}
                failed={transState.failed}
                current={transState.current}
                color="var(--accent-tertiary)"
              />
            )}
          </CardBody>
          {transState.log && transState.log.length > 0 && <LogPanel entries={transState.log} />}
        </Card>

        {/* ═══ 批量分析 ═══ */}
        <Card>
          <CardHeader icon="fa-brain" iconColor="var(--accent)" title="AI 批量分析" desc="遍历已提取文本的文章，生成结构化分析摘要" />
          <CardBody>
            <Button
              variant="primary"
              onClick={handleAnalyze}
              loading={analyzing}
              icon="fa-play"
            >
              开始批量分析
            </Button>
            {analyState.total > 0 && (
              <ProgressBar
                done={analyState.done}
                total={analyState.total}
                failed={analyState.failed}
                current={analyState.current}
                color="var(--accent)"
              />
            )}
          </CardBody>
          {analyState.log && analyState.log.length > 0 && <LogPanel entries={analyState.log} />}
        </Card>

        {/* ═══ 自动构筑逻辑链 ═══ */}
        <Card>
          <CardHeader icon="fa-diagram-project" iconColor="var(--accent-purple)" title="自动构筑逻辑链" desc="基于已分析事件的关键词自动分组，AI 命名后创建逻辑链" />
          <CardBody>
            <Button
              variant="purple"
              onClick={handleBuildChains}
              loading={chaining}
              icon="fa-play"
            >
              自动构筑
            </Button>
            {chainState.total_groups > 0 && (
              <ProgressBar
                done={chainState.chains_created}
                total={chainState.total_groups}
                current={chainState.current}
                color="var(--accent-purple)"
              />
            )}
            {chainState.chains_created > 0 && !chaining && (
              <div style={{ fontSize: 11, color: 'var(--accent-tertiary)', display: 'flex', alignItems: 'center', gap: 4 }}>
                <i className="fas fa-check-circle" />
                完成 {chainState.chains_created} 个链
              </div>
            )}
          </CardBody>
          {chainState.log && chainState.log.length > 0 && <LogPanel entries={chainState.log} />}
        </Card>
      </div>

      {/* ── AI 语义处理 ── */}
      <div style={{
        marginTop: 16,
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
        gap: 16,
      }}>
        <AICard
          icon="fa-tags"
          color="var(--accent-tertiary)"
          title="AI 关键词提取"
          desc="从文章正文提取技术关键词，替代硬编码映射表"
          state={kwState}
          running={kwRunning}
          onClick={handleKeywords}
          label="提取关键词"
        />
        <AICard
          icon="fa-folder-tree"
          color="var(--accent)"
          title="AI 智能分类"
          desc="自动归类文章细粒度领域 + 生成标签"
          state={clsState}
          running={clsRunning}
          onClick={handleClassify}
          label="智能分类"
        />
        <AICard
          icon="fa-star"
          color="var(--accent-orange)"
          title="AI 优先级评分"
          desc="AI 综合评估文章重要性、时效性、影响力"
          state={scoreState}
          running={scoreRunning}
          onClick={handleScore}
          label="智能评分"
        />
        <AICard
          icon="fa-object-group"
          color="var(--accent-purple)"
          title="智能事件重聚类"
          desc="AI 重新判定文章归属事件，修正误聚类"
          state={reclState}
          running={reclRunning}
          onClick={handleRecluster}
          label="重聚类"
        />
        <AICard
          icon="fa-file-lines"
          color="var(--accent-green)"
          title="事件摘要生成"
          desc="为多篇文章的事件生成综合 AI 摘要"
          state={esState}
          running={esRunning}
          onClick={handleSummarizeEvents}
          label="生成摘要"
        />
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

// ── AI 卡片组件 ──
function AICard({ icon, color, title, desc, state, running, onClick, label }: {
  icon: string; color: string; title: string; desc: string; state: BatchState; running: boolean; onClick: () => void; label: string;
}) {
  return (
    <Card>
      <CardHeader icon={icon} iconColor={color} title={title} desc={desc} />
      <CardBody>
        <Button
          onClick={onClick}
          loading={running}
          variant={color === 'var(--accent-tertiary)' ? 'green' : color === 'var(--accent-purple)' ? 'purple' : color === 'var(--accent-orange)' ? 'orange' : 'primary'}
          icon="fa-play"
        >
          {label}
        </Button>
        {state.total > 0 && (
          <ProgressBar
            done={state.done}
            total={state.total}
            failed={state.failed}
            current={state.current}
            color={color}
          />
        )}
      </CardBody>
      {state.log && state.log.length > 0 && <LogPanel entries={state.log} />}
    </Card>
  );
}
