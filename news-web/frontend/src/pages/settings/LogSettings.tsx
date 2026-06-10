import { useEffect, useState, useRef } from 'react';

export default function LogSettings() {
  const [lines, setLines] = useState<string[]>([]);
  const [total, setTotal] = useState(0);
  const [level, setLevel] = useState('');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const fetchLogs = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ lines: '200' });
      if (level) params.set('level', level);
      if (search) params.set('search', search);
      const r = await fetch(`/api/logs?${params}`);
      const d = await r.json();
      setLines(d.lines || []);
      setTotal(d.total || 0);
    } catch { setLines([]); }
    setLoading(false);
  };

  useEffect(() => { fetchLogs(); }, [level, search]);

  // 自动刷新
  useEffect(() => {
    if (!autoRefresh) return;
    const timer = setInterval(fetchLogs, 3000);
    return () => clearInterval(timer);
  }, [autoRefresh, level, search]);

  // 自动滚到底部
  useEffect(() => {
    if (scrollRef.current && (autoRefresh || loading)) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines, autoRefresh, loading]);

  const clearLogs = async () => {
    if (!confirm('确认清空所有日志？此操作不可恢复。')) return;
    await fetch('/api/logs/clear', { method: 'DELETE' });
    fetchLogs();
  };

  return (
    <div className="settings-container">
      <div className="settings-card">
        <div className="card-header">
          <h3><i className="fas fa-terminal" /> 操作日志</h3>
          <p className="card-description">
            实时查看服务端运行日志（{total} 行总计）— 抓取进度 / 翻译状态 / 错误追踪
          </p>
        </div>
        <div className="card-body">
          {/* 工具栏 */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            <select className="form-select-sm" value={level}
              onChange={e => setLevel(e.target.value)}>
              <option value="">全部级别</option>
              <option value="INFO">INFO</option>
              <option value="WARNING">WARNING</option>
              <option value="ERROR">ERROR</option>
              <option value="DEBUG">DEBUG</option>
            </select>
            <input className="form-control" placeholder="关键词搜索..."
              value={search} onChange={e => setSearch(e.target.value)}
              style={{ width: 200, padding: '4px 8px', fontSize: 12 }} />
            <button className="btn btn-secondary" onClick={() => { setLevel(''); setSearch(''); }}
              style={{ padding: '4px 10px', fontSize: 11 }}>
              <i className="fas fa-eraser" /> 清除过滤
            </button>
            <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', color: 'var(--text-secondary)' }}>
              <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)}
                style={{ accentColor: 'var(--accent)' }} />
              自动刷新 (3s)
            </label>
            <div style={{ flex: 1 }} />
            <button className="btn btn-secondary" onClick={fetchLogs} disabled={loading}
              style={{ padding: '4px 10px', fontSize: 11 }}>
              <i className={`fas fa-${loading ? 'spinner fa-spin' : 'sync-alt'}`} /> 刷新
            </button>
            <button className="btn btn-danger-sm" onClick={clearLogs}
              style={{ padding: '4px 10px', fontSize: 11 }}>
              <i className="fas fa-trash-alt" /> 清空
            </button>
          </div>

          {/* 日志内容 */}
          <div ref={scrollRef} style={{
            background: '#050508', border: '1px solid var(--border)', borderRadius: 8,
            padding: 12, maxHeight: 500, overflow: 'auto',
            fontFamily: 'var(--font-mono)', fontSize: 11, lineHeight: 1.6,
          }}>
            {lines.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 24 }}>
                {loading ? '加载中...' : '暂无日志'}
              </div>
            ) : (
              lines.map((line, i) => {
                let color = 'var(--text-secondary)';
                if (line.includes('ERROR')) color = 'var(--accent-red)';
                else if (line.includes('WARNING')) color = 'var(--accent-orange)';
                else if (line.includes('[Pipeline]')) color = 'var(--accent)';
                else if (line.includes('翻译') || line.includes('translate')) color = 'var(--accent-tertiary)';
                else if (line.includes('抓取') || line.includes('fetch')) color = 'var(--accent)';
                return (
                  <div key={i} style={{ color, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                    {line}
                  </div>
                );
              })
            )}
          </div>

          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 6 }}>
            显示 {lines.length} / {total} 行 · 日志文件: logs/news-web.log
          </div>
        </div>
      </div>

      <div className="settings-card">
        <div className="card-header">
          <h3><i className="fas fa-info-circle" /> 日志说明</h3>
        </div>
        <div className="card-body">
          <div className="info-list">
            <div className="info-item"><i className="fas fa-circle" style={{ color: 'var(--accent)', fontSize: 8 }} /> <strong style={{ color: 'var(--accent)' }}>蓝色</strong> — 管道操作（抓取/下载/AI 分析）</div>
            <div className="info-item"><i className="fas fa-circle" style={{ color: 'var(--accent-tertiary)', fontSize: 8 }} /> <strong style={{ color: 'var(--accent-tertiary)' }}>绿色</strong> — 翻译相关操作</div>
            <div className="info-item"><i className="fas fa-circle" style={{ color: 'var(--accent-red)', fontSize: 8 }} /> <strong style={{ color: 'var(--accent-red)' }}>红色</strong> — 错误信息</div>
            <div className="info-item"><i className="fas fa-circle" style={{ color: 'var(--accent-orange)', fontSize: 8 }} /> <strong style={{ color: 'var(--accent-orange)' }}>黄色</strong> — 警告信息</div>
            <div className="info-item"><i className="fas fa-sync-alt" /> 开启自动刷新可实时监控管道运行状态</div>
          </div>
        </div>
      </div>
    </div>
  );
}
