import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import type { Dispatch, SetStateAction } from 'react';
import { api } from '../../api/client';
import type { BatchRetryState } from '../../types';

interface CacheStatus {
  checked_at: string;
  cache_dir: string;
  summary: {
    total_articles: number;
    with_url: number;
    cached_db: number;
    cached_disk: number;
    missing_disk: number;
    orphan_files: number;
    with_text: number;
    with_translation: number;
    pending_download: number;
    failed_download: number;
    en_articles: number;
  };
  recent: { id: number; title: string; source: string; fetched_at: string }[];
  uncached_articles: { id: number; title: string; source: string }[];
  uncached_count: number;
}

interface CacheFetchState {
  running: boolean;
  total: number;
  done: number;
  failed: number;
  current: string;
  log: string[];
}

interface Props {
  cachePath: string; setCachePath: Dispatch<SetStateAction<string>>;
}

export default function CacheSettings({ cachePath, setCachePath }: Props) {
  const navigate = useNavigate();
  const [status, setStatus] = useState<CacheStatus | null>(null);
  const [checking, setChecking] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [fetchState, setFetchState] = useState<CacheFetchState>({ running: false, total: 0, done: 0, failed: 0, current: '', log: [] });
  const [fetching, setFetching] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval>>();

  // 批量重试状态（跨页面可见）
  const [batchRetryState, setBatchRetryState] = useState<BatchRetryState>({ running: false, total: 0, done: 0, failed: 0, current: '', log: [] });
  const batchRetryTimerRef = useRef<ReturnType<typeof setInterval>>();

  const handleCheck = async () => {
    setChecking(true);
    try {
      const d = await api.getCacheStatus();
      setStatus(d as unknown as CacheStatus);
    } catch { setStatus(null); }
    setChecking(false);
  };

  const handleVerify = async () => {
    setVerifying(true);
    const r = await fetch('/api/cache/verify', { method: 'POST' });
    const d = await r.json();
    alert(d.message || '开始校验');
    setVerifying(false);
  };

  const handleCleanOrphan = async () => {
    if (!confirm('确定清理磁盘上所有无对应数据库记录的孤立缓存文件？')) return;
    setCleaning(true);
    const r = await fetch('/api/cache/orphan', { method: 'DELETE' });
    const d = await r.json();
    alert(d.message || '清理完成');
    handleCheck();
    setCleaning(false);
  };

  // 启动缓存抓取
  const handleStartFetch = async () => {
    setFetching(true);
    try {
      await api.startCacheFetch();
      timerRef.current = setInterval(pollFetch, 2000);
    } catch { setFetching(false); }
  };

  // 轮询抓取状态
  const pollFetch = async () => {
    try {
      const s = await api.getCacheFetchStatus();
      setFetchState(s as unknown as CacheFetchState);
      if (!(s as unknown as CacheFetchState).running) {
        clearInterval(timerRef.current);
        setFetching(false);
        handleCheck(); // 刷新状态
      }
    } catch { clearInterval(timerRef.current); setFetching(false); }
  };

  // 检查是否有未缓存文章时自动提示
  useEffect(() => {
    if (status && status.uncached_count > 0 && !fetchState.running) {
      setFetching(false);
    }
  }, [status]);

  // 挂载时检查是否有运行中的批量重试 + 轮询
  useEffect(() => {
    const checkAndPoll = async () => {
      try {
        const s = await api.getBatchRetryStatus();
        setBatchRetryState(s);
        if (s.running) {
          batchRetryTimerRef.current = setInterval(async () => {
            try {
              const s2 = await api.getBatchRetryStatus();
              setBatchRetryState(s2);
              if (!s2.running) clearInterval(batchRetryTimerRef.current);
            } catch { clearInterval(batchRetryTimerRef.current); }
          }, 2000);
        }
      } catch { /* ignore */ }
    };
    checkAndPoll();
    return () => clearInterval(batchRetryTimerRef.current);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const s = status?.summary;

  return (
    <div className="settings-container">
      <div className="settings-card">
        <div className="card-header">
          <h3><i className="fas fa-archive" /> 内容缓存</h3>
          <p className="card-description">下载的文章 HTML 文件和提取的文本存放目录 — 留空则为数据库同级的 content/ 目录</p>
        </div>
        <div className="card-body">
          <div className="form-group">
            <label className="form-label"><i className="fas fa-folder" /> 缓存目录</label>
            <input className="form-control" value={cachePath} onChange={e => setCachePath(e.target.value)}
              placeholder="留空自动推导 (backend/data/content)" />
            <div className="form-text">
              <i className="fas fa-info-circle" /> 每个文章保存为 <code>{'{id}'}.html</code>。提取后的文本存储在数据库 text_content 列。
            </div>
          </div>
        </div>
      </div>

      {/* 缓存状态检查 */}
      <div className="settings-card">
        <div className="card-header">
          <h3><i className="fas fa-heartbeat" /> 缓存健康检查</h3>
          <p className="card-description">诊断磁盘文件完整性、DB 记录一致性、翻译覆盖率（仅统计 RSS 新闻）</p>
        </div>
        <div className="card-body">
          {/* 批量重试进度横幅（跨页面可见） */}
          {batchRetryState.running && (
            <div style={{
              marginBottom: 16,
              padding: '12px 16px',
              background: 'rgba(0, 212, 255, 0.08)',
              borderRadius: 8,
              border: '1px solid rgba(0, 212, 255, 0.2)',
              fontSize: 12,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <i className="fas fa-spinner fa-spin" style={{ color: 'var(--accent)', fontSize: 14 }} />
                <span style={{ fontWeight: 600, color: 'var(--accent)' }}>
                  批量重试中: {batchRetryState.done}/{batchRetryState.total}
                  ({batchRetryState.total > 0 ? Math.round(batchRetryState.done / batchRetryState.total * 100) : 0}%)
                </span>
                {batchRetryState.failed > 0 && (
                  <span style={{ color: 'var(--accent-red)', fontSize: 11 }}>失败 {batchRetryState.failed}</span>
                )}
                <a
                  onClick={(e) => { e.preventDefault(); navigate('/fetch'); }}
                  style={{ marginLeft: 'auto', color: 'var(--accent)', textDecoration: 'underline', cursor: 'pointer', fontSize: 11 }}
                >
                  查看详情 <i className="fas fa-external-link-alt" style={{ fontSize: 9 }} />
                </a>
              </div>
              <div style={{ height: 4, background: 'var(--bg-primary)', borderRadius: 2, overflow: 'hidden' }}>
                <div style={{
                  height: '100%', borderRadius: 2, transition: 'width 0.3s',
                  width: `${batchRetryState.total > 0 ? (batchRetryState.done / batchRetryState.total) * 100 : 0}%`,
                  background: 'var(--accent)',
                }} />
              </div>
            </div>
          )}

          <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
            <button className="btn btn-primary" onClick={handleCheck} disabled={checking}>
              <i className={`fas fa-${checking ? 'spinner fa-spin' : 'stethoscope'}`} />
              {' '}{checking ? '检查中...' : '检查缓存状态'}
            </button>
            <button className="btn btn-secondary" onClick={handleVerify} disabled={verifying}
              style={{ padding: '8px 16px', fontSize: 13 }}>
              <i className={`fas fa-${verifying ? 'spinner fa-spin' : 'check-double'}`} />
              {' '}校验文件完整性
            </button>
            <button className="btn btn-danger-sm" onClick={handleCleanOrphan} disabled={cleaning}
              style={{ padding: '8px 16px', fontSize: 13 }}>
              <i className="fas fa-broom" /> 清理孤立文件
            </button>
          </div>

          {s && (
            <>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 12 }}>
                检查时间: {status!.checked_at.slice(0, 19).replace('T', ' ')} · 缓存目录: <code style={{ color: 'var(--accent)' }}>{status!.cache_dir}</code>
              </div>

              {/* 统计卡片 */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
                <StatCard label="总文章" value={s.total_articles} icon="fa-newspaper" />
                <StatCard label="已缓存 (DB)" value={s.cached_db} icon="fa-database" color={s.cached_db < s.total_articles * 0.5 ? 'var(--accent-orange)' : 'var(--accent-tertiary)'} />
                <StatCard label="磁盘文件" value={s.cached_disk} icon="fa-hdd" color={s.cached_disk < s.cached_db ? 'var(--accent-orange)' : 'var(--accent-tertiary)'} />
                <StatCard label="文本已提取" value={s.with_text} icon="fa-file-alt" />
                <StatCard label="已翻译" value={s.with_translation} icon="fa-language" color={s.en_articles > 0 && s.with_translation < s.en_articles ? 'var(--accent-orange)' : 'var(--accent-tertiary)'} />
                <StatCard label="下载失败" value={s.failed_download} icon="fa-exclamation-triangle" color={s.failed_download > 0 ? 'var(--accent-red)' : 'var(--text-muted)'} />
                <StatCard label="磁盘缺失" value={s.missing_disk} icon="fa-unlink" color={s.missing_disk > 0 ? 'var(--accent-red)' : 'var(--text-muted)'} />
                <StatCard label="孤立文件" value={s.orphan_files} icon="fa-question-circle" color={s.orphan_files > 0 ? 'var(--accent-orange)' : 'var(--text-muted)'} />
              </div>

              {/* 失败文章快速操作 */}
              {s.failed_download > 0 && !batchRetryState.running && (
                <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <i className="fas fa-redo" style={{ color: 'var(--accent-red)', fontSize: 10 }} />
                  <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                    {s.failed_download} 篇下载失败 —{' '}
                    <a onClick={(e) => { e.preventDefault(); navigate('/fetch'); }}
                       style={{ color: 'var(--accent)', cursor: 'pointer', textDecoration: 'underline' }}>
                      前往数据采集页重试
                    </a>
                  </span>
                </div>
              )}

              {/* 覆盖率进度条 */}
              <div style={{ marginTop: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
                  <span>缓存覆盖率</span>
                  <span>{s.total_articles > 0 ? Math.round((s.cached_db / s.total_articles) * 100) : 0}%</span>
                </div>
                <div style={{ height: 6, background: 'var(--bg-primary)', borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{
                    height: '100%', borderRadius: 3, transition: 'width 0.6s ease',
                    width: `${s.total_articles > 0 ? (s.cached_db / s.total_articles) * 100 : 0}%`,
                    background: s.cached_db / Math.max(s.total_articles, 1) > 0.7 ? 'var(--gradient-accent)'
                      : s.cached_db / Math.max(s.total_articles, 1) > 0.4 ? 'linear-gradient(90deg, #ffb74d, #00d4ff)'
                      : 'var(--gradient-secondary)',
                  }} />
                </div>
              </div>

              {/* 未缓存文章提示 */}
              {status!.uncached_count > 0 && (
                <div style={{
                  marginTop: 16, padding: '12px 16px', background: 'rgba(255, 183, 77, 0.1)',
                  border: '1px solid rgba(255, 183, 77, 0.3)', borderRadius: 8,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                    <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--accent-orange)' }}>
                      <i className="fas fa-exclamation-triangle" style={{ marginRight: 6 }} />
                      {status!.uncached_count} 篇文章未缓存
                    </span>
                    <button
                      className="btn btn-primary"
                      style={{ padding: '6px 14px', fontSize: 12 }}
                      onClick={handleStartFetch}
                      disabled={fetching || fetchState.running}
                    >
                      <i className={`fas fa-${fetching || fetchState.running ? 'spinner fa-spin' : 'download'}`} />
                      {' '}{fetchState.running ? `抓取中 ${fetchState.done}/${fetchState.total}` : '开始缓存'}
                    </button>
                  </div>

                  {/* 抓取进度 */}
                  {fetchState.running && (
                    <div style={{ marginBottom: 8 }}>
                      <div style={{ height: 4, background: 'var(--bg-primary)', borderRadius: 2, overflow: 'hidden', marginBottom: 4 }}>
                        <div style={{
                          height: '100%', borderRadius: 2, transition: 'width 0.3s',
                          width: `${fetchState.total > 0 ? (fetchState.done / fetchState.total) * 100 : 0}%`,
                          background: 'var(--accent)',
                        }} />
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        {fetchState.current} · 失败 {fetchState.failed}
                      </div>
                    </div>
                  )}

                  {/* 未缓存文章列表 */}
                  <div style={{ maxHeight: 120, overflow: 'auto', fontSize: 11 }}>
                    {status!.uncached_articles.slice(0, 10).map(a => (
                      <div key={a.id} style={{ padding: '2px 0', color: 'var(--text-secondary)' }}>
                        #{a.id} {a.title.slice(0, 50)} <span style={{ color: 'var(--text-muted)' }}>({a.source})</span>
                      </div>
                    ))}
                    {status!.uncached_count > 10 && (
                      <div style={{ color: 'var(--text-muted)', padding: '4px 0' }}>
                        ... 还有 {status!.uncached_count - 10} 篇
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* 最近下载 */}
              {status!.recent.length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    最近下载
                  </div>
                  <div style={{ maxHeight: 160, overflow: 'auto' }}>
                    {status!.recent.map(a => (
                      <div key={a.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', fontSize: 11, borderBottom: '1px solid var(--border)' }}>
                        <span style={{ color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>#{a.id} {a.title}</span>
                        <span style={{ color: 'var(--text-muted)', marginLeft: 12, whiteSpace: 'nowrap' }}>{a.source} · {a.fetched_at?.slice(5, 16).replace('T', ' ')}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}

          {!s && !checking && (
            <div style={{ color: 'var(--text-muted)', fontSize: 12, textAlign: 'center', padding: 16 }}>
              <i className="fas fa-arrow-up" style={{ marginRight: 6 }} /> 点击"检查缓存状态"扫描当前缓存完整性
            </div>
          )}
        </div>
      </div>

      <div className="settings-card">
        <div className="card-header">
          <h3><i className="fas fa-info-circle" /> 缓存策略</h3>
        </div>
        <div className="card-body">
          <div className="info-list">
            <div className="info-item"><i className="fas fa-layer-group" /> 三级读取：DB 文本缓存 → 磁盘 HTML → 代理获取</div>
            <div className="info-item"><i className="fas fa-download" /> 管道步骤 3 自动下载新文章内容</div>
            <div className="info-item"><i className="fas fa-language" /> 英文文章自动检测并触发翻译（如翻译已启用）</div>
            <div className="info-item"><i className="fas fa-check-circle" /> 原文和译文独立存储，对照阅读不覆盖</div>
          </div>
        </div>
      </div>
    </div>
  );
}

const StatCard = ({ label, value, icon, color }: { label: string; value: number; icon: string; color?: string }) => (
  <div style={{
    background: 'var(--bg-card)', border: '1px solid var(--border)',
    borderRadius: 8, padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 10,
  }}>
    <i className={`fas ${icon}`} style={{ color: color || 'var(--accent)', fontSize: 16, width: 22, textAlign: 'center' }} />
    <div>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 700, color: color || 'var(--text-primary)' }}>{value}</div>
    </div>
  </div>
);
