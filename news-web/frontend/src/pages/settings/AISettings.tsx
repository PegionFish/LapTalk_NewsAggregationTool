import { useState, type Dispatch, type SetStateAction } from 'react';
import { api } from '../../api/client';

interface Props {
  baseUrl: string; setBaseUrl: Dispatch<SetStateAction<string>>;
  apiKey: string; setApiKey: Dispatch<SetStateAction<string>>;
  model: string; setModel: Dispatch<SetStateAction<string>>;
  enableThinking: boolean; setEnableThinking: Dispatch<SetStateAction<boolean>>;
  thinkingBudget: number; setThinkingBudget: Dispatch<SetStateAction<number>>;
  deepThinkingMaxTokens: number; setDeepThinkingMaxTokens: Dispatch<SetStateAction<number>>;
  jsonResponseFormat: boolean; setJsonResponseFormat: Dispatch<SetStateAction<boolean>>;
}

export default function AISettings({
  baseUrl, setBaseUrl,
  apiKey, setApiKey,
  model, setModel,
  enableThinking, setEnableThinking,
  thinkingBudget, setThinkingBudget,
  deepThinkingMaxTokens, setDeepThinkingMaxTokens,
  jsonResponseFormat, setJsonResponseFormat,
}: Props) {
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
          <p className="card-description">SiliconFlow DeepSeek V3.2 / OpenAI 兼容 API — 用于事件总结、文章分析、关键词/分类/评分与全景推理（支持 enable_thinking 与 160K 上下文）</p>
        </div>
        <div className="card-body">
          <div className="form-group">
            <label className="form-label"><i className="fas fa-link" /> API 地址</label>
            <input className="form-control" value={baseUrl} onChange={e => setBaseUrl(e.target.value)}
              placeholder="https://api.siliconflow.cn/v1" />
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
              placeholder="deepseek-ai/DeepSeek-V3.2" />
          </div>
          <div className="form-group">
            <label className="form-label"><i className="fas fa-lightbulb" /> 启用深度思考</label>
            <label className="switch-row">
              <input type="checkbox" checked={enableThinking} onChange={e => setEnableThinking(e.target.checked)} />
              <span>向 SiliconFlow 发送 enable_thinking=true，适合 DeepSeek V3.2 深度分析</span>
            </label>
            <div className="form-text">若使用不支持 thinking 的兼容端点，可关闭此项。</div>
          </div>
          <div className="form-grid two">
            <div className="form-group">
              <label className="form-label"><i className="fas fa-brain" /> 思维预算 token</label>
              <input className="form-control" type="number" min={128} max={32768} value={thinkingBudget}
                onChange={e => setThinkingBudget(Number(e.target.value))} />
              <div className="form-text">SiliconFlow thinking_budget 范围：128-32768。</div>
            </div>
            <div className="form-group">
              <label className="form-label"><i className="fas fa-file-alt" /> 深度输出上限 token</label>
              <input className="form-control" type="number" min={1024} value={deepThinkingMaxTokens}
                onChange={e => setDeepThinkingMaxTokens(Number(e.target.value))} />
              <div className="form-text">用于单篇分析、全景排序、逻辑链构建等高质量输出。</div>
            </div>
          </div>
          <div className="form-group">
            <label className="form-label"><i className="fas fa-code" /> 强制 JSON 输出</label>
            <label className="switch-row">
              <input type="checkbox" checked={jsonResponseFormat} onChange={e => setJsonResponseFormat(e.target.checked)} />
              <span>对关键词、分类、评分、事件关系、全景推理使用 response_format=json_object</span>
            </label>
            <div className="form-text">可减少结构化任务解析失败；非 OpenAI 兼容端点如报错可关闭。</div>
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
            <div className="info-item"><i className="fas fa-check" /> 默认使用 SiliconFlow DeepSeek V3.2，可充分利用 160K 上下文</div>
            <div className="info-item"><i className="fas fa-check" /> 单篇分析、关键词、分类、评分优先保留完整正文</div>
            <div className="info-item"><i className="fas fa-check" /> 全景排序与逻辑链构建使用深思提示 + JSON object 输出</div>
            <div className="info-item"><i className="fas fa-check" /> 如配置但不可用，管道跳过分析步骤不阻塞抓取</div>
          </div>
        </div>
      </div>
    </div>
  );
}
