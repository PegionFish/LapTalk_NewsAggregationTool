import { useState, type Dispatch, type SetStateAction } from 'react';
import { api } from '../../api/client';

interface Props {
  baseUrl: string; setBaseUrl: Dispatch<SetStateAction<string>>;
  apiKey: string; setApiKey: Dispatch<SetStateAction<string>>;
  model: string; setModel: Dispatch<SetStateAction<string>>;
}

export default function AISettings({ baseUrl, setBaseUrl, apiKey, setApiKey, model, setModel }: Props) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await api.testAi();
      if (r.ok) {
        setTestResult({ ok: true, message: `连接成功 · 模型: ${r.model} · 响应: ${r.response || '-'}` });
      } else {
        setTestResult({ ok: false, message: r.error || '未知错误' });
      }
    } catch (e) {
      setTestResult({ ok: false, message: (e as Error).message });
    }
    setTesting(false);
  };

  return (
    <div className="settings-container">
      <div className="settings-card">
        <div className="card-header">
          <h3><i className="fas fa-brain" /> AI 分析配置</h3>
          <p className="card-description">OpenAI 兼容 API — 用于事件总结和关系推荐（支持 DeepSeek / Ollama / vLLM 等兼容端点）</p>
        </div>
        <div className="card-body">
          <div className="form-group">
            <label className="form-label"><i className="fas fa-link" /> API 地址</label>
            <input className="form-control" value={baseUrl} onChange={e => setBaseUrl(e.target.value)}
              placeholder="https://api.openai.com/v1" />
          </div>
          <div className="form-group">
            <label className="form-label"><i className="fas fa-key" /> API Key</label>
            <input className="form-control" type="password" value={apiKey} onChange={e => setApiKey(e.target.value)}
              placeholder="sk-..." />
            <div className="form-text">留空则跳过 AI 分析步骤。保存后 Key 以 *** 掩码显示。</div>
          </div>
          <div className="form-group">
            <label className="form-label"><i className="fas fa-robot" /> 模型</label>
            <input className="form-control" value={model} onChange={e => setModel(e.target.value)}
              placeholder="gpt-4o-mini" />
          </div>

          {/* 测试按钮 */}
          <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 10 }}>
            <button onClick={handleTest} disabled={testing}
              className="btn btn-secondary" style={{ padding: '8px 18px', fontSize: 13 }}>
              <i className={`fas fa-${testing ? 'spinner fa-spin' : 'plug'}`} />
              {' '}{testing ? '测试中...' : '测试连接'}
            </button>
            {testResult && (
              <span style={{
                fontSize: 12, fontWeight: 500,
                color: testResult.ok ? 'var(--accent-tertiary)' : 'var(--accent-red)',
              }}>
                <i className={`fas fa-${testResult.ok ? 'check-circle' : 'exclamation-circle'}`} style={{ marginRight: 4 }} />
                {testResult.message}
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="settings-card">
        <div className="card-header">
          <h3><i className="fas fa-info-circle" /> 说明</h3>
        </div>
        <div className="card-body">
          <div className="info-list">
            <div className="info-item"><i className="fas fa-check" /> 支持所有 OpenAI 兼容端点（DeepSeek、Ollama、vLLM 等）</div>
            <div className="info-item"><i className="fas fa-check" /> 用于管道步骤 4：AI 重命名事件标题 + 推荐事件关系</div>
            <div className="info-item"><i className="fas fa-check" /> 如配置但不可用，管道跳过分析步骤不阻塞抓取</div>
          </div>
        </div>
      </div>
    </div>
  );
}
