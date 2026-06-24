import { useState, useEffect, useCallback } from 'react';
import { api } from '../../api/client';
import type { AiConfig, AiEndpointProfile, AiProvider, AiTestResult } from '../../types';

interface Props {
  baseUrl: string; setBaseUrl: (v: string) => void;
  apiKey: string; setApiKey: (v: string) => void;
  model: string; setModel: (v: string) => void;
  enableThinking: boolean; setEnableThinking: (v: boolean) => void;
  thinkingBudget: number; setThinkingBudget: (v: number) => void;
  deepThinkingMaxTokens: number; setDeepThinkingMaxTokens: (v: number) => void;
  jsonResponseFormat: boolean; setJsonResponseFormat: (v: boolean) => void;
  translationEnabled: boolean; setTranslationEnabled: (v: boolean) => void;
  translationBaseUrl: string; setTranslationBaseUrl: (v: string) => void;
  translationApiKey: string; setTranslationApiKey: (v: string) => void;
  translationModel: string; setTranslationModel: (v: string) => void;
}

export default function AISettings({
  baseUrl, setBaseUrl,
  apiKey, setApiKey,
  model, setModel,
  enableThinking, setEnableThinking,
  thinkingBudget, setThinkingBudget,
  deepThinkingMaxTokens, setDeepThinkingMaxTokens,
  jsonResponseFormat, setJsonResponseFormat,
  translationEnabled, setTranslationEnabled,
  translationBaseUrl, setTranslationBaseUrl,
  translationApiKey, setTranslationApiKey,
  translationModel, setTranslationModel,
}: Props) {
  const [aiConfig, setAiConfig] = useState<AiConfig | null>(null);
  const [testResults, setTestResults] = useState<Record<string, AiTestResult>>({});
  const [testing, setTesting] = useState<string[]>([]);
  const [testingAll, setTestingAll] = useState(false);
  const [showApiKey, setShowApiKey] = useState<Record<string, boolean>>({});
  const [showImport, setShowImport] = useState(false);
  const [importText, setImportText] = useState('');
  const [expandedProfile, setExpandedProfile] = useState<string | null>(null);

  useEffect(() => {
    api.getAiConfig().then(setAiConfig).catch(() => {});
  }, []);

  const providers = aiConfig?.providers ?? {};
  const profiles = aiConfig?.profiles ?? [];
  const settings = aiConfig?.settings;

  const getProviderForProfile = useCallback(
    (profile: AiEndpointProfile): AiProvider | undefined => providers[profile.provider_id],
    [providers],
  );

  const handleTest = async (targets: string[]) => {
    if (targets[0] === 'all') setTestingAll(true);
    else setTesting(prev => [...prev, ...targets]);
    setTestResults({});
    try {
      const resp = await api.testAiConfig(targets);
      setTestResults(resp.results);
      if (aiConfig) {
        const newProviders = { ...aiConfig.providers };
        for (const [name, result] of Object.entries(resp.results)) {
          for (const p of Object.values(newProviders)) {
            if (name in (p.models || {})) {
              newProviders[p.id] = { ...p, status: result.ok ? 'ok' : 'error' };
            }
          }
        }
        setAiConfig({ ...aiConfig, providers: newProviders });
      }
    } catch (e) {
      console.error('测试失败:', e);
    }
    setTestingAll(false);
    setTesting([]);
  };

  const handleCopyKey = (key: string) => {
    navigator.clipboard.writeText(key).catch(() => {});
  };

  const handleExport = () => {
    if (!aiConfig) return;
    const exportData = {
      providers: Object.fromEntries(
        Object.entries(aiConfig.providers).map(([id, p]) => [
          id,
          { base_url: p.base_url, api_key: p.api_key, models: p.models },
        ])
      ),
      settings: aiConfig.settings,
      exported_at: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ai-config-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = () => {
    try {
      const data = JSON.parse(importText);
      if (data.providers) {
        const updateData: Record<string, unknown> = {};
        for (const [, p] of Object.entries(data.providers) as [string, { base_url?: string; api_key?: string; models?: Record<string, string> }][]) {
          if (p.base_url) updateData.openai_base_url = p.base_url;
          if (p.api_key) updateData.openai_api_key = p.api_key;
          if (p.models?.analyze) updateData.openai_model = p.models.analyze;
          if (p.models?.simple) updateData.simple_model = p.models.simple;
          if (p.models?.clean) updateData.clean_model = p.models.clean;
          if (p.models?.translation) updateData.translation_model = p.models.translation;
        }
        if (data.settings) {
          Object.assign(updateData, data.settings);
        }
        api.updateAiConfig(updateData).then(setAiConfig).catch(() => {});
      }
      setShowImport(false);
      setImportText('');
    } catch {
      alert('导入格式错误');
    }
  };

  const StatusIcon = ({ profile }: { profile: AiEndpointProfile }) => {
    const provider = getProviderForProfile(profile);
    if (!provider) return <i className="fas fa-circle" style={{ color: 'var(--text-muted)', fontSize: 8 }} />;
    const result = testResults[profile.id];
    if (result) {
      return result.ok
        ? <i className="fas fa-check-circle" style={{ color: 'var(--accent-tertiary)', fontSize: 10 }} />
        : <i className="fas fa-exclamation-circle" style={{ color: 'var(--accent-red)', fontSize: 10 }} />;
    }
    return <i className="fas fa-circle" style={{ color: 'var(--text-muted)', fontSize: 8 }} />;
  };

  return (
    <div className="settings-container">
      {/* 全局操作栏 */}
      <div className="ai-config-toolbar">
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button
            className="btn btn-secondary"
            onClick={() => handleTest(['all'])}
            disabled={testingAll}
            style={{ fontSize: 12, padding: '6px 14px' }}
          >
            <i className={`fas fa-${testingAll ? 'spinner fa-spin' : 'plug'}`} />
            {' '}{testingAll ? '测试中...' : '全部测试'}
          </button>
          <button className="btn btn-secondary" onClick={handleExport} style={{ fontSize: 12, padding: '6px 14px' }}>
            <i className="fas fa-download" /> 导出
          </button>
          <button className="btn btn-secondary" onClick={() => setShowImport(!showImport)} style={{ fontSize: 12, padding: '6px 14px' }}>
            <i className="fas fa-upload" /> 导入
          </button>
        </div>
      </div>

      {showImport && (
        <div className="ai-config-import">
          <textarea
            className="form-control"
            rows={4}
            placeholder="粘贴导出的 JSON 配置..."
            value={importText}
            onChange={e => setImportText(e.target.value)}
          />
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button className="btn btn-primary" onClick={handleImport} style={{ fontSize: 12, padding: '6px 14px' }}>
              <i className="fas fa-check" /> 应用
            </button>
            <button className="btn btn-secondary" onClick={() => { setShowImport(false); setImportText(''); }} style={{ fontSize: 12, padding: '6px 14px' }}>
              取消
            </button>
          </div>
        </div>
      )}

      {/* 端点分组卡片 */}
      {profiles.map(profile => {
        const provider = getProviderForProfile(profile);
        const isExpanded = expandedProfile === profile.id;
        const result = testResults[profile.id];
        const isTestingThis = testing.includes(profile.id);

        return (
          <div key={profile.id} className="ai-config-card">
            <div
              className="ai-config-card-header"
              onClick={() => setExpandedProfile(isExpanded ? null : profile.id)}
            >
              <div className="ai-config-card-title">
                <StatusIcon profile={profile} />
                <h3>{profile.name}</h3>
                <span className="ai-config-model-badge">{profile.model_id}</span>
              </div>
              <div className="ai-config-card-actions">
                <span className="ai-config-provider-name">{provider?.name || profile.provider_id}</span>
                <button
                  className="btn btn-secondary"
                  onClick={e => { e.stopPropagation(); handleTest([profile.id]); }}
                  disabled={isTestingThis}
                  style={{ fontSize: 11, padding: '4px 10px' }}
                >
                  <i className={`fas fa-${isTestingThis ? 'spinner fa-spin' : 'plug'}`} />
                  {' '}{isTestingThis ? '测试中' : '测试'}
                </button>
                <i className={`fas fa-chevron-${isExpanded ? 'up' : 'down'}`} style={{ color: 'var(--text-muted)', fontSize: 10 }} />
              </div>
            </div>

            <div className="ai-config-card-desc">{profile.description}</div>

            {result && (
              <div className={`ai-config-test-result ${result.ok ? 'success' : 'error'}`}>
                <i className={`fas fa-${result.ok ? 'check-circle' : 'exclamation-circle'}`} />
                {result.ok
                  ? `连接成功 · 模型: ${result.model} · ${result.response || result.translation || 'OK'}`
                  : `连接失败 · ${result.error}`
                }
              </div>
            )}

            {isExpanded && provider && (
              <div className="ai-config-card-body">
                <div className="form-group">
                  <label className="form-label"><i className="fas fa-link" /> API 地址</label>
                  <input className="form-control" value={provider.base_url} readOnly />
                  <div className="form-text">端点地址继承自 Provider「{provider.name}」</div>
                </div>
                <div className="form-group">
                  <label className="form-label"><i className="fas fa-key" /> API Key</label>
                  <div className="ai-config-key-row">
                    <input
                      className="form-control"
                      type={showApiKey[profile.id] ? 'text' : 'password'}
                      value={showApiKey[profile.id] ? provider.api_key : provider.api_key_masked}
                      readOnly
                    />
                    <button
                      className="btn btn-secondary"
                      onClick={() => setShowApiKey(prev => ({ ...prev, [profile.id]: !prev[profile.id] }))}
                      style={{ padding: '6px 10px', fontSize: 11 }}
                    >
                      <i className={`fas fa-${showApiKey[profile.id] ? 'eye-slash' : 'eye'}`} />
                    </button>
                    <button
                      className="btn btn-secondary"
                      onClick={() => handleCopyKey(provider.api_key)}
                      style={{ padding: '6px 10px', fontSize: 11 }}
                    >
                      <i className="fas fa-copy" />
                    </button>
                  </div>
                  <div className="form-text">在「通用设置」或「AI 翻译」中修改</div>
                </div>
                <div className="form-group">
                  <label className="form-label"><i className="fas fa-robot" /> 模型</label>
                  <input className="form-control" value={profile.model_id} readOnly />
                  <div className="form-text">{profile.description}</div>
                </div>
              </div>
            )}
          </div>
        );
      })}

      {/* AI 翻译端点（独立配置，兼容旧流程） */}
      <div className="ai-config-card">
        <div className="ai-config-card-header" onClick={() => setExpandedProfile(expandedProfile === 'translation独立' ? null : 'translation独立')}>
          <div className="ai-config-card-title">
            <i className="fas fa-circle" style={{ color: translationEnabled ? 'var(--accent-tertiary)' : 'var(--text-muted)', fontSize: 8 }} />
            <h3>AI 翻译</h3>
            <span className="ai-config-model-badge">{translationModel || '未配置'}</span>
          </div>
          <div className="ai-config-card-actions">
            <span style={{ fontSize: 11, color: translationEnabled ? 'var(--accent-tertiary)' : 'var(--text-muted)' }}>
              {translationEnabled ? '已启用' : '已禁用'}
            </span>
            <i className={`fas fa-chevron-${expandedProfile === 'translation独立' ? 'up' : 'down'}`} style={{ color: 'var(--text-muted)', fontSize: 10 }} />
          </div>
        </div>
        {expandedProfile === 'translation独立' && (
          <div className="ai-config-card-body">
            <div className="form-group">
              <label className="form-check">
                <input type="checkbox" checked={translationEnabled} onChange={e => setTranslationEnabled(e.target.checked)} />
                <span className="form-check-label">启用 AI 翻译</span>
              </label>
            </div>
            <div className="form-group">
              <label className="form-label"><i className="fas fa-link" /> API 地址</label>
              <input className="form-control" value={translationBaseUrl} onChange={e => setTranslationBaseUrl(e.target.value)}
                placeholder="https://api.siliconflow.cn/v1" />
            </div>
            <div className="form-group">
              <label className="form-label"><i className="fas fa-key" /> API Key</label>
              <input className="form-control" type="password" value={translationApiKey} onChange={e => setTranslationApiKey(e.target.value)}
                placeholder="sk-..." />
            </div>
            <div className="form-group">
              <label className="form-label"><i className="fas fa-robot" /> 模型</label>
              <input className="form-control" value={translationModel} onChange={e => setTranslationModel(e.target.value)}
                placeholder="deepseek-ai/DeepSeek-V3.2" />
            </div>
          </div>
        )}
      </div>

      {/* 全局 AI 设置 */}
      <div className="settings-card">
        <div className="card-header">
          <h3><i className="fas fa-cog" /> 全局设置</h3>
        </div>
        <div className="card-body">
          <div className="form-group">
            <label className="form-label"><i className="fas fa-lightbulb" /> 启用深度思考</label>
            <label className="switch-row">
              <input type="checkbox" checked={enableThinking} onChange={e => setEnableThinking(e.target.checked)} />
              <span>向 SiliconFlow 发送 enable_thinking=true</span>
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
        </div>
      </div>

      {/* 说明 */}
      <div className="settings-card">
        <div className="card-header">
          <h3><i className="fas fa-info-circle" /> 说明</h3>
        </div>
        <div className="card-body">
          <div className="info-list">
            <div className="info-item"><i className="fas fa-check" /> 入口级配置：所有 AI 端点共享主 Provider 的 base_url 和 api_key</div>
            <div className="info-item"><i className="fas fa-check" /> 独立模型：分析/清洗/轻量任务/翻译可分别指定模型</div>
            <div className="info-item"><i className="fas fa-check" /> 清洗端点支持独立 API 地址（需在 config.json 中配置 clean_base_url）</div>
            <div className="info-item"><i className="fas fa-check" /> 全部测试：一键验证所有端点的连通性</div>
            <div className="info-item"><i className="fas fa-check" /> 配置导入/导出：JSON 格式，便于跨环境迁移</div>
          </div>
        </div>
      </div>
    </div>
  );
}
