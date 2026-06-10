import { useState, type Dispatch, type SetStateAction } from 'react';
import { api } from '../../api/client';

interface Props {
  enabled: boolean; setEnabled: Dispatch<SetStateAction<boolean>>;
  baseUrl: string; setBaseUrl: Dispatch<SetStateAction<string>>;
  apiKey: string; setApiKey: Dispatch<SetStateAction<string>>;
  model: string; setModel: Dispatch<SetStateAction<string>>;
}

export default function TranslationSettings({
  enabled, setEnabled, baseUrl, setBaseUrl, apiKey, setApiKey, model, setModel,
}: Props) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await api.testTranslation();
      if (r.ok) {
        setTestResult({ ok: true, message: `连接成功 · 模型: ${r.model} · 「${r.original}」→「${r.translation || ''}」` });
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
          <h3><i className="fas fa-language" /> AI 翻译配置</h3>
          <p className="card-description">
            独立于 AI 分析的翻译 API — 支持所有 OpenAI 兼容端点，英文科技新闻自动译中文
          </p>
        </div>
        <div className="card-body">
          <div className="form-group">
            <label className="form-check">
              <input type="checkbox" checked={enabled}
                onChange={e => setEnabled(e.target.checked)} />
              <span className="form-check-label">启用 AI 翻译（英文文章自动译中文）</span>
            </label>
            <div className="form-text">翻译在管道中后台静默执行，篇间延迟 5 秒防超限。原文和译文独立存储，对照阅读。</div>
          </div>
          <div className="form-group">
            <label className="form-label"><i className="fas fa-link" /> API 地址</label>
            <input className="form-control" value={baseUrl} onChange={e => setBaseUrl(e.target.value)}
              placeholder="https://api.openai.com/v1" />
          </div>
          <div className="form-group">
            <label className="form-label"><i className="fas fa-key" /> API Key</label>
            <input className="form-control" type="password" value={apiKey} onChange={e => setApiKey(e.target.value)}
              placeholder="sk-..." />
            <div className="form-text">翻译 API 独立配置，可复用 AI 分析 Key 或指向其他兼容端点。</div>
          </div>
          <div className="form-group">
            <label className="form-label"><i className="fas fa-microchip" /> 模型</label>
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
          <h3><i className="fas fa-cogs" /> 翻译参数</h3>
        </div>
        <div className="card-body">
          <div className="info-list">
            <div className="info-item"><i className="fas fa-thermometer-half" /> temperature = 0.05（极低温度保证翻译一致性）</div>
            <div className="info-item"><i className="fas fa-text-width" /> max_tokens = 8192（覆盖绝大多数科技新闻长度）</div>
            <div className="info-item"><i className="fas fa-clock" /> 篇间延迟 5 秒（防止 API 超限）</div>
            <div className="info-item"><i className="fas fa-shield-alt" /> 保留技术名词原文（GPU、API、NVIDIA 等），人名使用中文通用译名</div>
          </div>
        </div>
      </div>
    </div>
  );
}
