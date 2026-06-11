import { useEffect, useState, useRef, useCallback } from 'react';
import { api } from '../api/client';
import type { Stats } from '../types';
import DashboardCards from '../components/DashboardCards';

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

  const transTimer = useRef<ReturnType<typeof setInterval>>();
  const analyTimer  = useRef<ReturnType<typeof setInterval>>();
  const chainTimer  = useRef<ReturnType<typeof setInterval>>();
  const kwTimer = useRef<ReturnType<typeof setInterval>>();
  const clsTimer = useRef<ReturnType<typeof setInterval>>();
  const scoreTimer = useRef<ReturnType<typeof setInterval>>();
  const reclTimer = useRef<ReturnType<typeof setInterval>>();
  const esTimer = useRef<ReturnType<typeof setInterval>>();

  const poll = useCallback((fn: () => Promise<unknown>, setter: (v: unknown) => void, stop: () => void, timer: ReturnType<typeof useRef<ReturnType<typeof setInterval>>>) => {
    fn().then(v => { setter(v); if (!(v as BatchState).running) { stop(); clearInterval(timer.current); } }).catch(stop);
  }, []);

  const pollTranslate = useCallback(() => poll(
    api.getBatchTranslateStatus, v => setTransState(v as BatchState), () => setTranslating(false), transTimer), []);
  const pollAnalyze = useCallback(() => poll(
    api.getBatchAnalyzeStatus, v => setAnalyState(v as BatchState), () => setAnalyzing(false), analyTimer), []);
  const pollChains = useCallback(() => poll(
    api.getBuildChainsStatus, v => setChainState(v as ChainState), () => setChaining(false), chainTimer), []);

  useEffect(() => { api.getStats().then(setStats).catch(() => setStats(null)).finally(() => setLoading(false)); }, []);

  useEffect(() => {
    // 挂载时恢复所有 AI 任务状态（切换页面后轮询继续）
    api.getBatchTranslateStatus().then((s: unknown) => { const st = s as BatchState; if (st.running) { setTranslating(true); transTimer.current = setInterval(pollTranslate, 2000); } else setTransState(st); }).catch(() => {});
    api.getBatchAnalyzeStatus().then((s: unknown)  => { const st = s as BatchState; if (st.running) { setAnalyzing(true);  analyTimer.current  = setInterval(pollAnalyze, 2000);  } else setAnalyState(st);  }).catch(() => {});
    api.getBuildChainsStatus().then((s: unknown)    => { const st = s as ChainState; if (st.running) { setChaining(true);  chainTimer.current  = setInterval(pollChains, 2000);  } else setChainState(st);  }).catch(() => {});
    api.getBatchKeywordsStatus().then((s: unknown)  => { const st = s as BatchState; if (st.running) { setKwRunning(true); kwTimer.current = setInterval(pollKw, 2000); } else setKwState(st); }).catch(() => {});
    api.getBatchClassifyStatus().then((s: unknown)  => { const st = s as BatchState; if (st.running) { setClsRunning(true); clsTimer.current = setInterval(pollCls, 2000); } else setClsState(st); }).catch(() => {});
    api.getBatchScoreStatus().then((s: unknown)     => { const st = s as BatchState; if (st.running) { setScoreRunning(true); scoreTimer.current = setInterval(pollSc, 2000); } else setScoreState(st); }).catch(() => {});
    api.getBatchReclusterStatus().then((s: unknown) => { const st = s as BatchState; if (st.running) { setReclRunning(true); reclTimer.current = setInterval(pollRecl, 2000); } else setReclState(st); }).catch(() => {});
    api.getBatchSummarizeEventsStatus().then((s: unknown) => { const st = s as BatchState; if (st.running) { setEsRunning(true); esTimer.current = setInterval(pollEs, 2000); } else setEsState(st); }).catch(() => {});
    api.getBatchAiFullStatus().then((s: unknown)    => { const st = s as BatchState; if (st.running) { setFullRunning(true); fullTimer.current = setInterval(pollFull, 2000); } else setFullState(st); }).catch(() => {});
    return () => {
      [transTimer, analyTimer, chainTimer, kwTimer, clsTimer, scoreTimer, reclTimer, esTimer, fullTimer].forEach(t => clearInterval(t.current));
    };
  }, []); // eslint-disable-line

  const startPoll = (starter: () => Promise<unknown>, poller: () => void, timer: ReturnType<typeof useRef<ReturnType<typeof setInterval>>>, setRunning: (v: boolean) => void) => async () => {
    setRunning(true);
    try {
      const res = await starter() as { ok?: boolean; message?: string };
      if (res && res.ok === false) {
        // 后端拒绝请求（如任务已在运行中），显示提示后重置
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

  const [fullRunning, setFullRunning] = useState(false);
  const [fullState, setFullState] = useState<BatchState>(emptyBatch);
  const fullTimer = useRef<ReturnType<typeof setInterval>>(undefined);
  const pollFull = useCallback(() => poll(api.getBatchAiFullStatus, v => {const s=v as BatchState; setFullState(s); if(!s.running){setFullRunning(false);clearInterval(fullTimer.current)}},(()=>setFullRunning(false)),fullTimer),[]);
  const handleFullAi = startPoll(api.startBatchAiFull, pollFull, fullTimer, setFullRunning);

  const progressPct = (done: number, total: number) => total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <div style={{ padding: 24, overflow: 'auto', flex: 1 }}>
      <h2 style={{ marginBottom: 20 }}>📊 仪表盘</h2>
      {toast && (
        <div style={{ marginBottom: 16, padding: '10px 16px', background: 'rgba(255,193,7,0.12)', border: '1px solid rgba(255,193,7,0.3)', borderRadius: 8, color: '#ffc107', fontSize: 13, display: 'flex', alignItems: 'center', gap: 8 }}>
          <i className="fas fa-exclamation-triangle" />
          {toast}
        </div>
      )}
      <DashboardCards stats={stats} loading={loading} />

      {/* ═══ AI 批量处理 ───────────────────────────────────── */}
      <div style={{ marginTop: 24, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>

        {/* ═══ 一键全流程 ═══ grid-column:1/-1 强制全宽 */}
        <div style={{ ...card, gridColumn: '1 / -1', background: 'linear-gradient(135deg, rgba(0,212,255,0.08), rgba(129,199,132,0.05))', border: '1px solid rgba(0,212,255,0.25)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14 }}>
            <i className="fas fa-rocket" style={{ color: 'var(--accent)', fontSize: 22 }} />
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 700, fontSize: 15 }}>一键全流程 AI 处理</div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>翻译 → 分析 → 关键词 → 分类 → 评分 → 聚类 → 摘要 → 构筑逻辑链</div>
            </div>
            <button onClick={handleFullAi} disabled={fullRunning}
              style={{ border: 'none', borderRadius: 8, padding: '10px 28px', fontWeight: 700, fontSize: 14, display: 'flex', alignItems: 'center', gap: 8, whiteSpace: 'nowrap', cursor: fullRunning ? 'default' : 'pointer', background: fullRunning ? 'var(--bg-card)' : 'var(--accent)', color: fullRunning ? 'var(--text-muted)' : '#000' }}>
              {fullRunning ? <><i className="fas fa-spinner fa-spin" /> 运行中...</> : <><i className="fas fa-play" /> 启动全流程</>}
            </button>
          </div>
          {(fullRunning || fullState.total > 0) && (
            <div style={{ maxWidth: '100%' }}>
              <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginBottom: 6 }}>
                {fullRunning ? <i className="fas fa-spinner fa-spin" style={{ marginRight: 6 }} /> : <i className="fas fa-check-circle" style={{ color: 'var(--accent-tertiary)', marginRight: 6 }} />}
                步骤 {fullState.done}/{fullState.total || 8} · {fullState.current || '等待中...'}
              </div>
              {fullState.total > 0 && (
                <div style={{ height: 5, background: 'var(--bg-primary)', borderRadius: 3, overflow: 'hidden', marginBottom: 10 }}>
                  <div style={{ height: '100%', borderRadius: 3, background: 'var(--accent)', transition: 'width 0.5s ease', width: `${fullState.total>0?Math.round(fullState.done/fullState.total*100):0}%` }} />
                </div>
              )}
              {/* 分步状态指示器 */}
              {fullState.steps && fullState.steps.length > 0 && (
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 6 }}>
                  {fullState.steps.map((s, i) => {
                    const icon = s.status === 'done' ? '✅' : s.status === 'failed' ? '❌' : s.status === 'running' ? '⏳' : '⬜';
                    const bg = s.status === 'done' ? 'rgba(129,199,132,0.12)' : s.status === 'failed' ? 'rgba(239,83,80,0.12)' : s.status === 'running' ? 'rgba(0,212,255,0.12)' : 'transparent';
                    const border = s.status === 'done' ? '1px solid rgba(129,199,132,0.3)' : s.status === 'failed' ? '1px solid rgba(239,83,80,0.3)' : s.status === 'running' ? '1px solid rgba(0,212,255,0.4)' : '1px solid var(--border)';
                    return (
                      <div key={i} style={{ fontSize: 11, padding: '3px 8px', borderRadius: 12, background: bg, border, display: 'flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap' }}>
                        <span>{icon}</span>
                        <span style={{ color: s.status === 'running' ? 'var(--accent)' : 'var(--text-secondary)' }}>{s.name}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
          {fullState.log?.length! > 0 && <LogPanel entries={fullState.log!} />}
        </div>

        {/* ═══ 批量翻译 ═══ */}
        <div style={card}>
          <div style={cardHeader}>
            <i className="fas fa-language" style={{ color: 'var(--accent-tertiary)', fontSize: 18 }} />
            <div><div style={{ fontWeight: 600, fontSize: 14 }}>AI 批量翻译</div><div style={{ fontSize: 11, color: 'var(--text-muted)' }}>遍历英文文章 HTML，调用 API 翻译为中文</div></div>
          </div>
          <div style={cardBody}>
            <Btn onClick={handleTranslate} disabled={translating} color="var(--accent-tertiary)" label="开始批量翻译" running={translating} />
            {transState.total > 0 && <Progress done={transState.done} total={transState.total} failed={transState.failed} current={transState.current} pct={progressPct(transState.done, transState.total)} color="var(--accent-tertiary)" />}
          </div>
          {transState.log?.length! > 0 && <LogPanel entries={transState.log!} />}
        </div>

        {/* ═══ 批量分析 ═══ */}
        <div style={card}>
          <div style={cardHeader}>
            <i className="fas fa-brain" style={{ color: 'var(--accent)', fontSize: 18 }} />
            <div><div style={{ fontWeight: 600, fontSize: 14 }}>AI 批量分析</div><div style={{ fontSize: 11, color: 'var(--text-muted)' }}>遍历已提取文本的文章，生成结构化分析摘要</div></div>
          </div>
          <div style={cardBody}>
            <Btn onClick={handleAnalyze} disabled={analyzing} color="var(--accent)" label="开始批量分析" running={analyzing} />
            {analyState.total > 0 && <Progress done={analyState.done} total={analyState.total} failed={analyState.failed} current={analyState.current} pct={progressPct(analyState.done, analyState.total)} color="var(--accent)" />}
          </div>
          {analyState.log?.length! > 0 && <LogPanel entries={analyState.log!} />}
        </div>

        {/* ═══ 自动构筑逻辑链 ═══ */}
        <div style={card}>
          <div style={cardHeader}>
            <i className="fas fa-diagram-project" style={{ color: 'var(--accent-purple)', fontSize: 18 }} />
            <div><div style={{ fontWeight: 600, fontSize: 14 }}>自动构筑逻辑链</div><div style={{ fontSize: 11, color: 'var(--text-muted)' }}>基于已分析事件的关键词自动分组，AI 命名后创建逻辑链</div></div>
          </div>
          <div style={cardBody}>
            <Btn onClick={handleBuildChains} disabled={chaining} color="var(--accent-purple)" label="自动构筑" running={chaining} />
            {chainState.total_groups > 0 && <Progress done={chainState.chains_created} total={chainState.total_groups} failed={0} current={chainState.current} pct={Math.round(chainState.total_groups > 0 ? (chainState.chains_created / chainState.total_groups) * 100 : 0)} color="var(--accent-purple)" />}
            {chainState.chains_created > 0 && !chaining && <div style={{ fontSize: 11, color: 'var(--accent-tertiary)', marginLeft: 12 }}><i className="fas fa-check-circle" /> 完成 {chainState.chains_created} 个链</div>}
          </div>
          {chainState.log?.length! > 0 && <LogPanel entries={chainState.log!} />}
        </div>
      </div>

      {/* ── AI 语义处理 ── */}
      <div style={{ marginTop: 16, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
        <Card icon="fa-tags" color="var(--accent-tertiary)" title="AI 关键词提取" desc="从文章正文提取技术关键词，替代硬编码映射表" state={kwState} running={kwRunning} onClick={handleKeywords} label="提取关键词" />
        <Card icon="fa-folder-tree" color="var(--accent)" title="AI 智能分类" desc="自动归类文章细粒度领域 + 生成标签" state={clsState} running={clsRunning} onClick={handleClassify} label="智能分类" />
        <Card icon="fa-star" color="var(--accent-orange)" title="AI 优先级评分" desc="AI 综合评估文章重要性、时效性、影响力" state={scoreState} running={scoreRunning} onClick={handleScore} label="智能评分" />
        <Card icon="fa-object-group" color="var(--accent-purple)" title="智能事件重聚类" desc="AI 重新判定文章归属事件，修正误聚类" state={reclState} running={reclRunning} onClick={handleRecluster} label="重聚类" />
        <Card icon="fa-file-lines" color="var(--accent-green)" title="事件摘要生成" desc="为多篇文章的事件生成综合 AI 摘要" state={esState} running={esRunning} onClick={handleSummarizeEvents} label="生成摘要" />
      </div>

      {stats && (
        <div style={{ marginTop: 24, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 16 }}>
          {/* 分类概览 */}
          <div style={{ background: 'var(--bg-secondary)', borderRadius: 10, padding: 20 }}>
            <h3 style={{ fontSize: 14, margin: '0 0 12px 0' }}>数据分类</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              {Object.entries(stats.by_category).map(([cat, count]) => (
                <div key={cat} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                  <span style={{ width: 90, color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{cat}</span>
                  <div style={{ flex: 1, background: 'var(--bg-card)', borderRadius: 4, height: 14, overflow: 'hidden' }}>
                    <div style={{ width: `${Math.min((count / stats.articles) * 100, 100)}%`, height: '100%', background: 'var(--accent-tertiary)', borderRadius: 4, minWidth: 3 }} />
                  </div>
                  <span style={{ width: 32, textAlign: 'right', fontSize: 11 }}>{count}</span>
                </div>
              ))}
            </div>
          </div>

          {/* 来源分布 — 按实际媒体名 */}
          <div style={{ background: 'var(--bg-secondary)', borderRadius: 10, padding: 20 }}>
            <h3 style={{ fontSize: 14, margin: '0 0 12px 0' }}>媒体来源 TOP15</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {Object.entries(stats.by_source || {})
                .sort((a, b) => b[1] - a[1])
                .slice(0, 15)
                .map(([source, count]) => (
                  <div key={source} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                    <span style={{ width: 100, color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={source}>{source}</span>
                    <div style={{ flex: 1, background: 'var(--bg-card)', borderRadius: 4, height: 12, overflow: 'hidden' }}>
                      <div style={{ width: `${Math.min((count / stats.articles) * 100, 100)}%`, height: '100%', background: 'var(--accent)', borderRadius: 4, minWidth: 3 }} />
                    </div>
                    <span style={{ width: 32, textAlign: 'right', fontSize: 11 }}>{count}</span>
                  </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── 子组件 ────────────────────────────────────────────

const Btn = ({ onClick, disabled, color, label, running }: { onClick: () => void; disabled: boolean; color: string; label: string; running: boolean }) => (
  <button onClick={onClick} disabled={disabled} style={{ ...actionBtn, background: disabled ? 'var(--bg-card)' : color, color: disabled ? 'var(--text-muted)' : (color === 'var(--accent-purple)' ? '#fff' : '#000'), cursor: disabled ? 'default' : 'pointer' }}>
    {running ? <><i className="fas fa-spinner fa-spin" /> 运行中</> : <><i className="fas fa-play" /> {label}</>}
  </button>
);

const Progress = ({ done, total, failed, current, pct, color }: { done: number; total: number; failed: number; current: string; pct: number; color: string }) => (
  <div style={{ flex: 1, marginLeft: 12 }}>
    <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginBottom: 4, fontWeight: 500 }}>{done}/{total} · {failed > 0 ? `${failed} 失败 ` : ''}{pct}%</div>
    <div style={{ height: 5, background: 'var(--bg-primary)', borderRadius: 3, overflow: 'hidden' }}>
      <div style={{ height: '100%', borderRadius: 3, transition: 'width 0.5s ease', width: `${pct}%`, background: color }} />
    </div>
    {current && <div style={{ fontSize: 10, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginTop: 3 }}>{current}</div>}
  </div>
);

const LogPanel = ({ entries }: { entries: string[] }) => (
  <div style={logStyle}>
    {entries.slice(-40).map((line, i) => {
      const c = line.includes('✅') ? logGreen : line.includes('❌') ? logRed : line.includes('⚠') || line.includes('⏭') ? logYellow : logBlue;
      return <div key={i} style={c}>{line}</div>;
    })}
  </div>
);

// ── 样式 ──────────────────────────────────────────────
const card: React.CSSProperties = { background: 'var(--bg-secondary)', borderRadius: 10, padding: 20, border: '1px solid var(--border)', display: 'flex', flexDirection: 'column' };
const cardHeader: React.CSSProperties = { display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 14 };
const cardBody: React.CSSProperties = { display: 'flex', alignItems: 'center' };
const actionBtn: React.CSSProperties = { border: 'none', borderRadius: 8, padding: '10px 20px', fontWeight: 600, fontSize: 13, display: 'flex', alignItems: 'center', gap: 8, whiteSpace: 'nowrap', transition: 'var(--transition-fast)' };

const logStyle: React.CSSProperties = { background: '#0d1117', borderRadius: 6, padding: '8px 10px', maxHeight: 180, overflowY: 'auto', fontFamily: 'Consolas, "Courier New", monospace', fontSize: 10, lineHeight: 1.7, marginTop: 12, border: '1px solid var(--border)' };
const logGreen: React.CSSProperties  = { color: '#81c784' };
const logBlue: React.CSSProperties   = { color: '#90caf9' };
const logYellow: React.CSSProperties = { color: '#ffb74d' };
const logRed: React.CSSProperties    = { color: '#ef5350' };

// 通用卡片组件 — 5 张 AI 卡片复用
const Card = ({ icon, color, title, desc, state, running, onClick, label }: {
  icon: string; color: string; title: string; desc: string; state: BatchState; running: boolean; onClick: () => void; label: string;
}) => (
  <div style={card}>
    <div style={cardHeader}>
      <i className={`fas ${icon}`} style={{ color, fontSize: 18 }} />
      <div><div style={{ fontWeight: 600, fontSize: 14 }}>{title}</div><div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{desc}</div></div>
    </div>
    <div style={cardBody}>
      <Btn onClick={onClick} disabled={running} color={color} label={label} running={running} />
      {state.total > 0 && <Progress done={state.done} total={state.total} failed={state.failed} current={state.current} pct={state.total > 0 ? Math.round((state.done / state.total) * 100) : 0} color={color} />}
    </div>
    {state.log?.length! > 0 && <LogPanel entries={state.log!} />}
  </div>
);
