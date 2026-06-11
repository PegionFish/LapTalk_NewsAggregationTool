import { useState, type Dispatch, type SetStateAction } from 'react';
import { api } from '../../api/client';

interface Props {
  dbPath: string; setDbPath: Dispatch<SetStateAction<string>>;
  userAgent: string; setUserAgent: Dispatch<SetStateAction<string>>;
  pipelineEnabled: boolean; setPipelineEnabled: Dispatch<SetStateAction<boolean>>;
  pipelineRunning: boolean;
  pipelineStatus: { last_run?: string | null; last_status?: string | null };
  onTriggerPipeline: () => void;
  proxyEnabled: boolean; setProxyEnabled: Dispatch<SetStateAction<boolean>>;
  proxyUrl: string; setProxyUrl: Dispatch<SetStateAction<string>>;
}

export default function GeneralSettings({
  dbPath, setDbPath, userAgent, setUserAgent,
  pipelineEnabled, setPipelineEnabled, pipelineRunning, pipelineStatus, onTriggerPipeline,
  proxyEnabled, setProxyEnabled, proxyUrl, setProxyUrl,
}: Props) {
  const [testingProxy, setTestingProxy] = useState(false);
  const [proxyTestResult, setProxyTestResult] = useState('');

  const handleTestProxy = async () => {
    setTestingProxy(true);
    setProxyTestResult('');
    try {
      const r = await api.testProxy();
      setProxyTestResult(r.ok
        ? `✅ ${r.message || '连接成功'}`
        : `❌ ${r.error || '连接失败'}`);
    } catch (e) {
      setProxyTestResult(`❌ 请求失败: ${(e as Error).message}`);
    }
    setTestingProxy(false);
  };

  return (
    <div className="settings-container">
      {/* 数据库 */}
      <div className="settings-card">
        <div className="card-header">
          <h3><i className="fas fa-database" /> 数据库</h3>
          <p className="card-description">配置 SQLite 数据库文件路径，支持本地路径或 NAS 共享挂载点</p>
        </div>
        <div className="card-body">
          <div className="form-group">
            <label className="form-label"><i className="fas fa-folder-open" /> 数据库路径</label>
            <input className="form-control" value={dbPath} onChange={e => setDbPath(e.target.value)}
              placeholder="留空自动推导为 backend/data/news.db" />
            <div className="form-text">修改后需重启服务生效。当前生效路径见右上角状态栏。</div>
          </div>
        </div>
      </div>

      {/* 抓取调度 */}
      <div className="settings-card">
        <div className="card-header">
          <h3><i className="fas fa-clock" /> 抓取调度</h3>
          <p className="card-description">定时抓取 RSS 新闻管道（每天 10:00 / 17:00，数据库备份 03:00）</p>
        </div>
        <div className="card-body">
          <div className="form-group">
            <label className="form-check">
              <input type="checkbox" checked={pipelineEnabled}
                onChange={e => setPipelineEnabled(e.target.checked)} />
              <span className="form-check-label">启用定时抓取</span>
            </label>
          </div>
          <div style={{ marginTop: 12 }}>
            <button className="btn btn-success" onClick={onTriggerPipeline} disabled={pipelineRunning}>
              <i className={`fas fa-${pipelineRunning ? 'spinner fa-spin' : 'sync-alt'}`} />
              {' '}{pipelineRunning ? '抓取中...' : '手动抓取'}
            </button>
            {pipelineStatus.last_run && (
              <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-secondary)' }}>
                <i className="fas fa-history" /> 上次运行: {pipelineStatus.last_run?.slice(0, 19).replace('T', ' ')}
                <span style={{ marginLeft: 8, color: pipelineStatus.last_status === 'success' ? 'var(--accent-tertiary)' :
                  pipelineStatus.last_status === 'failed' ? 'var(--accent-red)' : 'var(--accent-orange)' }}>
                  {pipelineStatus.last_status === 'success' ? '✅ 成功' :
                   pipelineStatus.last_status === 'failed' ? '❌ 失败' : '⏳ 运行中'}
                </span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 网络 */}
      <div className="settings-card">
        <div className="card-header">
          <h3><i className="fas fa-globe" /> 网络</h3>
          <p className="card-description">HTTP 请求 User-Agent 标识，用于 RSS 抓取和页面内容下载</p>
        </div>
        <div className="card-body">
          <div className="form-group">
            <label className="form-label"><i className="fas fa-tag" /> User-Agent</label>
            <input className="form-control" value={userAgent} onChange={e => setUserAgent(e.target.value)}
              placeholder="Mozilla/5.0 ..." />
          </div>
          <div className="form-group" style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
            <label className="form-check">
              <input type="checkbox" checked={proxyEnabled}
                onChange={e => setProxyEnabled(e.target.checked)} />
              <span className="form-check-label">启用境外内容抓取代理</span>
            </label>
          </div>
          {proxyEnabled && (
            <>
              <div className="form-group" style={{ marginTop: 8 }}>
                <label className="form-label"><i className="fas fa-network-wired" /> 代理地址</label>
                <input className="form-control" value={proxyUrl} onChange={e => setProxyUrl(e.target.value)}
                  placeholder="http://127.0.0.1:7890" />
                <div className="form-text">支持 HTTP 和 SOCKS5 代理协议（如 socks5://127.0.0.1:1080）。仅对 RSS 抓取和页面下载生效，AI 分析/翻译不走代理。SOCKS5 需要安装 pip install PySocks。</div>
              </div>
              <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 10 }}>
                <button className="btn btn-outline" onClick={handleTestProxy} disabled={testingProxy}
                  style={{ padding: '6px 16px', fontSize: 12 }}>
                  <i className={`fas fa-${testingProxy ? 'spinner fa-spin' : 'plug'}`} />
                  {' '}{testingProxy ? '测试中...' : '测试代理 (访问 Google)'}
                </button>
                {proxyTestResult && (
                  <span style={{
                    fontSize: 11,
                    color: proxyTestResult.startsWith('✅') ? 'var(--accent-tertiary)' : 'var(--accent-red)',
                    fontWeight: 500,
                  }}>{proxyTestResult}</span>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
