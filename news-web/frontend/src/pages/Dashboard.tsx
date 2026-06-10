import { useEffect, useState, useRef, useCallback } from 'react';
import { api } from '../api/client';
import type { Stats } from '../types';
import DashboardCards from '../components/DashboardCards';

type BatchState = { running: boolean; total: number; done: number; failed: number; current: string };
type ChainState = { running: boolean; total_groups: number; chains_created: number; current: string };

const emptyChain: ChainState = { running: false, total_groups: 0, chains_created: 0, current: '' };

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);

  // 批量 AI 状态
  const [translating, setTranslating] = useState(false);
  const [transState, setTransState] = useState<BatchState>(emptyBatch);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyState, setAnalyState] = useState<BatchState>(emptyBatch);
  const [chaining, setChaining] = useState(false);
  const [chainState, setChainState] = useState<ChainState>(emptyChain);

  const transTimer = useRef<ReturnType<typeof setInterval>>();
  const analyTimer = useRef<ReturnType<typeof setInterval>>();
  const chainTimer = useRef<ReturnType<typeof setInterval>>();

  const pollTranslate = useCallback(() => {
    api.getBatchTranslateStatus().then(s => {
      setTransState(s as BatchState);
      if (!s.running) { setTranslating(false); clearInterval(transTimer.current); }
    }).catch(() => setTranslating(false));
  }, []);

  const pollAnalyze = useCallback(() => {
    api.getBatchAnalyzeStatus().then(s => {
      setAnalyState(s as BatchState);
      if (!s.running) { setAnalyzing(false); clearInterval(analyTimer.current); }
    }).catch(() => setAnalyzing(false));
  }, []);

  const pollChains = useCallback(() => {
    api.getBuildChainsStatus().then(s => {
      setChainState(s as ChainState);
      if (!s.running) { setChaining(false); clearInterval(chainTimer.current); }
    }).catch(() => setChaining(false));
  }, []);

  useEffect(() => {
    api.getStats().then(setStats).catch(() => setStats(null)).finally(() => setLoading(false));
  }, []);

  // 初次进入时检查是否有运行中的任务
  useEffect(() => {
    api.getBatchTranslateStatus().then((s: unknown) => {
      const st = s as BatchState;
      if (st.running) { setTranslating(true); transTimer.current = setInterval(pollTranslate, 2000); }
      else setTransState(st as BatchState);
    }).catch(() => {});
    api.getBatchAnalyzeStatus().then((s: unknown) => {
      const st = s as BatchState;
      if (st.running) { setAnalyzing(true); analyTimer.current = setInterval(pollAnalyze, 2000); }
      else setAnalyState(st as BatchState);
    }).catch(() => {});
    api.getBuildChainsStatus().then((s: unknown) => {
      const st = s as ChainState;
      if (st.running) { setChaining(true); chainTimer.current = setInterval(pollChains, 2000); }
      else setChainState(st as ChainState);
    }).catch(() => {});
    return () => { clearInterval(transTimer.current); clearInterval(analyTimer.current); clearInterval(chainTimer.current); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleTranslate = async () => {
    setTranslating(true);
    try {
      await api.startBatchTranslate();
      pollTranslate(); // 立即获取初始状态
      transTimer.current = setInterval(pollTranslate, 2000);
    } catch { setTranslating(false); }
  };

  const handleAnalyze = async () => {
    setAnalyzing(true);
    try {
      await api.startBatchAnalyze();
      pollAnalyze();
      analyTimer.current = setInterval(pollAnalyze, 2000);
    } catch { setAnalyzing(false); }
  };

  const handleBuildChains = async () => {
    setChaining(true);
    try {
      await api.startBuildChains();
      pollChains();
      chainTimer.current = setInterval(pollChains, 2000);
    } catch { setChaining(false); }
  };

  const progressPct = (done: number, total: number) =>
    total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <div style={{ padding: 24, overflow: 'auto', flex: 1 }}>
      <h2 style={{ marginBottom: 20 }}>📊 仪表盘</h2>
      <DashboardCards stats={stats} loading={loading} />

      {/* ── 批量 AI 处理 ── */}
      {stats && (
        <div style={{ marginTop: 24, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>

          {/* 批量翻译 */}
          <div style={card}>
            <div style={cardHeader}>
              <i className="fas fa-language" style={{ color: 'var(--accent-tertiary)', fontSize: 18 }} />
              <div>
                <div style={{ fontWeight: 600, fontSize: 14 }}>AI 批量翻译</div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>遍历英文文章 HTML，调用 API 翻译为中文</div>
              </div>
            </div>
            <div style={{ ...cardBody, justifyContent: 'space-between' }}>
              <button onClick={handleTranslate} disabled={translating}
                style={{
                  ...actionBtn,
                  background: translating ? 'var(--bg-card)' : 'var(--accent-tertiary)',
                  color: translating ? 'var(--text-muted)' : '#000',
                  cursor: translating ? 'default' : 'pointer',
                }}>
                {translating
                  ? <><i className="fas fa-spinner fa-spin" /> 翻译中</>
                  : <><i className="fas fa-play" /> 开始批量翻译</>}
              </button>
              {transState.total > 0 && (
                <div style={{ flex: 1, marginLeft: 12 }}>
                  <div style={progressText}>{transState.done}/{transState.total} · {transState.failed > 0 ? `${transState.failed} 失败 ` : ''}{progressPct(transState.done, transState.total)}%</div>
                  <div style={track}><div style={{ ...bar, width: `${progressPct(transState.done, transState.total)}%`, background: 'var(--accent-tertiary)' }} /></div>
                  {transState.current && <div style={{ fontSize: 10, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{transState.current}</div>}
                </div>
              )}
            </div>
          </div>

          {/* 批量分析 */}
          <div style={card}>
            <div style={cardHeader}>
              <i className="fas fa-brain" style={{ color: 'var(--accent)', fontSize: 18 }} />
              <div>
                <div style={{ fontWeight: 600, fontSize: 14 }}>AI 批量分析</div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>遍历已提取文本的文章，生成结构化分析摘要</div>
              </div>
            </div>
            <div style={{ ...cardBody, justifyContent: 'space-between' }}>
              <button onClick={handleAnalyze} disabled={analyzing}
                style={{
                  ...actionBtn,
                  background: analyzing ? 'var(--bg-card)' : 'var(--accent)',
                  color: analyzing ? 'var(--text-muted)' : '#000',
                  cursor: analyzing ? 'default' : 'pointer',
                }}>
                {analyzing
                  ? <><i className="fas fa-spinner fa-spin" /> 分析中</>
                  : <><i className="fas fa-play" /> 开始批量分析</>}
              </button>
              {analyState.total > 0 && (
                <div style={{ flex: 1, marginLeft: 12 }}>
                  <div style={progressText}>{analyState.done}/{analyState.total} · {analyState.failed > 0 ? `${analyState.failed} 失败 ` : ''}{progressPct(analyState.done, analyzeState.total)}%</div>
                  <div style={track}><div style={{ ...bar, width: `${progressPct(analyState.done, analyState.total)}%`, background: 'var(--accent)' }} /></div>
                  {analyState.current && <div style={{ fontSize: 10, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{analyState.current}</div>}
                </div>
              )}
            </div>
          </div>

          {/* 自动构筑逻辑链 */}
          <div style={card}>
            <div style={cardHeader}>
              <i className="fas fa-diagram-project" style={{ color: 'var(--accent-purple)', fontSize: 18 }} />
              <div>
                <div style={{ fontWeight: 600, fontSize: 14 }}>自动构筑逻辑链</div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>基于已分析事件的关键词自动分组，AI 命名后创建逻辑链</div>
              </div>
            </div>
            <div style={{ ...cardBody, justifyContent: 'space-between' }}>
              <button onClick={handleBuildChains} disabled={chaining}
                style={{
                  ...actionBtn,
                  background: chaining ? 'var(--bg-card)' : 'var(--accent-purple)',
                  color: chaining ? 'var(--text-muted)' : '#fff',
                  cursor: chaining ? 'default' : 'pointer',
                }}>
                {chaining
                  ? <><i className="fas fa-spinner fa-spin" /> 构筑中</>
                  : <><i className="fas fa-play" /> 自动构筑</>}
              </button>
              {chainState.total_groups > 0 && (
                <div style={{ flex: 1, marginLeft: 12 }}>
                  <div style={progressText}>{chainState.chains_created}/{chainState.total_groups} 组 · {Math.round(chainState.total_groups > 0 ? (chainState.chains_created / chainState.total_groups) * 100 : 0)}%</div>
                  <div style={track}><div style={{ ...bar, width: `${chainState.total_groups > 0 ? (chainState.chains_created / chainState.total_groups) * 100 : 0}%`, background: 'var(--accent-purple)' }} /></div>
                  {chainState.current && <div style={{ fontSize: 10, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{chainState.current}</div>}
                </div>
              )}
              {chainState.chains_created > 0 && !chaining && (
                <div style={{ fontSize: 11, color: 'var(--accent-tertiary)', marginLeft: 12 }}>
                  <i className="fas fa-check-circle" /> 完成 {chainState.chains_created} 个链
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 来源分布 */}
      {stats && (
        <div style={{ marginTop: 24, background: 'var(--bg-secondary)', borderRadius: 10, padding: 20 }}>
          <h3 style={{ fontSize: 15, marginBottom: 12 }}>来源分布</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {Object.entries(stats.by_category).map(([cat, count]) => (
              <div key={cat} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                <span style={{ width: 100, color: 'var(--text-secondary)' }}>{cat}</span>
                <div style={{ flex: 1, background: 'var(--bg-card)', borderRadius: 4, height: 16, overflow: 'hidden' }}>
                  <div style={{
                    width: `${(count / stats.articles) * 100}%`, height: '100%',
                    background: 'var(--accent)', borderRadius: 4, minWidth: 4
                  }} />
                </div>
                <span style={{ width: 40, textAlign: 'right' }}>{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

const emptyBatch: BatchState = { running: false, total: 0, done: 0, failed: 0, current: '' };

const card: React.CSSProperties = {
  background: 'var(--bg-secondary)', borderRadius: 10, padding: 20,
  border: '1px solid var(--border)', display: 'flex', flexDirection: 'column',
};
const cardHeader: React.CSSProperties = {
  display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 14,
};
const cardBody: React.CSSProperties = {
  display: 'flex', alignItems: 'center',
};
const actionBtn: React.CSSProperties = {
  border: 'none', borderRadius: 8, padding: '10px 20px', fontWeight: 600, fontSize: 13,
  display: 'flex', alignItems: 'center', gap: 8, whiteSpace: 'nowrap', transition: 'var(--transition-fast)',
};
const progressText: React.CSSProperties = { fontSize: 11, color: 'var(--text-secondary)', marginBottom: 4, fontWeight: 500 };
const track: React.CSSProperties = { height: 5, background: 'var(--bg-primary)', borderRadius: 3, overflow: 'hidden' };
const bar: React.CSSProperties = { height: '100%', borderRadius: 3, transition: 'width 0.5s ease' };
