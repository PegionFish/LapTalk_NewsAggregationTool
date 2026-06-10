import type { Dispatch, SetStateAction } from 'react';

interface Props {
  baseUrl: string; setBaseUrl: Dispatch<SetStateAction<string>>;
  apiKey: string; setApiKey: Dispatch<SetStateAction<string>>;
  model: string; setModel: Dispatch<SetStateAction<string>>;
}

export default function AISettings({ baseUrl, setBaseUrl, apiKey, setApiKey, model, setModel }: Props) {
  return (
    <div className="settings-container">
      <div className="settings-card">
        <div className="card-header">
          <h3><i className="fas fa-brain" /> AI 分析配置</h3>
          <p className="card-description">OpenAI 兼容 API — 用于事件总结和关系推荐（支持 DeepSeek / Ollama 等兼容端点）</p>
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
