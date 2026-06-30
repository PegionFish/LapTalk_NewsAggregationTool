import { useState, useEffect, useCallback } from 'react';
import { api } from '../../api/client';
import type { AiEndpointConfig, AiEndpointTestResult, AiSettingsResponse } from '../../types';

// 入口元数据（中文名 + 描述）
const ENDPOINT_META: Record<string, { name: string; description: string; group: string }> = {
  title_filter: { name: '标题初筛', description: 'RSS 抓取后的标题批量筛选，判断文章是否值得缓存', group: '数据采集' },
  article_processing: { name: '文章处理', description: '内容清洗 · 翻译 · 分析摘要 · KCS 合并', group: '文章处理' },
  event_pipeline: { name: '事件管线', description: '事件聚类 · 摘要生成 · 逻辑链构建', group: '事件管线' },
};
const GROUP_ORDER = ['数据采集', '文章处理', '事件管线'];

interface Props {}

export default function AISettings(_props: Props) {
  const [aiSettings, setAiSettings] = useState<AiSettingsResponse | null>(null);
  const [testResults, setTestResults] = useState<AiEndpointTestResult[]>([]);
  const [testingAll, setTestingAll] = useState(false);
  const [testingSingle, setTestingSingle] = useState<string | null>(null);
  const [expandedEndpoint, setExpandedEndpoint] = useState<string | null>(null);
  const [showApiKey, setShowApiKey] = useState<Record<string, boolean>>({});
  const [showImport, setShowImport] = useState<string | null>(null);
  const [importSource, setImportSource] = useState('');
  const [importFields, setImportFields] = useState<Record<string, boolean>>({
    base_url: true, api_key: false, model: true, params: false,
  });

  // 从后端加载入口级配置
  useEffect(() => {
    api.getAiSettings().then(setAiSettings).catch(() => {});
  }, []);

  const endpoints = aiSettings?.ai_endpoints ?? {};

  // 保存单个入口配置
  const handleSaveEndpoint = useCallback(async (key: string, data: Partial<AiEndpointConfig>) => {
    const updated = { ...endpoints, [key]: { ...endpoints[key], ...data } };
    try {
      const resp = await api.updateAiSettings({ ai_endpoints: updated });
      setAiSettings(resp);
    } catch (e) {
      console.error('保存失败:', e);
    }
  }, [endpoints]);

  // 测试所有入口
  const handleTestAll = async () => {
    setTestingAll(true);
    setTestResults([]);
    try {
      const resp = await api.testAiEndpoints();
      setTestResults(resp.results);
    } catch (e) {
      console.error('测试失败:', e);
    }
    setTestingAll(false);
  };

  // 测试单个入口
  const handleTestSingle = async (key: string) => {
    setTestingSingle(key);
    try {
      const resp = await api.testAiEndpoints(key);
      setTestResults(prev => {
        const filtered = prev.filter(r => r.endpoint_key !== key);
        return [...filtered, ...resp.results];
      });
    } catch (e) {
      console.error('测试失败:', e);
    }
    setTestingSingle(null);
  };

  // 导入配置
  const handleImport = (targetKey: string) => {
    if (!importSource || importSource === targetKey) return;
    const source = endpoints[importSource];
    if (!source) return;

    const update: Partial<AiEndpointConfig> = {};
    if (importFields.base_url) update.base_url = source.base_url;
    if (importFields.api_key) update.api_key = source.api_key;
    if (importFields.model) update.model = source.model;
    if (importFields.params) {
      update.enable_thinking = source.enable_thinking;
      update.thinking_budget = source.thinking_budget;
      update.deep_thinking_max_tokens = source.deep_thinking_max_tokens;
      update.json_response_format = source.json_response_format;
      update.target_lang = source.target_lang;
      update.max_tokens = source.max_tokens;
    }
    handleSaveEndpoint(targetKey, update);
    setShowImport(null);
  };

  // 获取测试结果
  const getResult = (key: string) => testResults.find(r => r.endpoint_key === key);

  // 按分组组织入口
  const grouped = GROUP_ORDER.map(group => ({
    group,
    items: Object.entries(endpoints)
      .filter(([key]) => ENDPOINT_META[key]?.group === group)
      .map(([key, config]) => ({ key, config, meta: ENDPOINT_META[key] })),
  })).filter(g => g.items.length > 0);

  return (
    <div className="settings-container">
      {/* 顶部操作栏 */}
      <div className="ai-config-toolbar">
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button className="btn btn-secondary" onClick={handleTestAll} disabled={testingAll}
            style={{ fontSize: 12, padding: '6px 14px' }}>
            <i className={`fas fa-${testingAll ? 'spinner fa-spin' : 'plug'}`} />
            {' '}{testingAll ? '测试中...' : '测试所有 AI 入口'}
          </button>
        </div>
      </div>

      {/* 按分组渲染入口卡片 */}
      {grouped.map(({ group, items }) => (
        <div key={group}>
          <div className="ai-config-group-title">{group}</div>
          {items.map(({ key, config: ep, meta }) => {
            const result = getResult(key);
            const isExpanded = expandedEndpoint === key;
            const isTesting = testingSingle === key;

            return (
              <div key={key} className="ai-config-card">
                {/* 卡片头 */}
                <div className="ai-config-card-header"
                  onClick={() => setExpandedEndpoint(isExpanded ? null : key)}>
                  <div className="ai-config-card-title">
                    <i className={`fas fa-circle`}
                      style={{ color: ep.enabled ? (result?.ok ? 'var(--accent-tertiary)' : result?.ok === false ? 'var(--accent-red)' : 'var(--text-muted)') : 'var(--text-muted)', fontSize: 8 }} />
                    <h3>{meta.name}</h3>
                    <span className="ai-config-model-badge">{ep.model || '未配置'}</span>
                  </div>
                  <div className="ai-config-card-actions">
                    <span style={{ fontSize: 11, color: ep.enabled ? 'var(--accent-tertiary)' : 'var(--text-muted)' }}>
                      {ep.enabled ? '已启用' : '已禁用'}
                    </span>
                    <button className="btn btn-secondary"
                      onClick={e => { e.stopPropagation(); handleTestSingle(key); }}
                      disabled={isTesting}
                      style={{ fontSize: 11, padding: '4px 10px' }}>
                      <i className={`fas fa-${isTesting ? 'spinner fa-spin' : 'plug'}`} />
                      {' '}{isTesting ? '测试中' : '测试'}
                    </button>
                    <i className={`fas fa-chevron-${isExpanded ? 'up' : 'down'}`}
                      style={{ color: 'var(--text-muted)', fontSize: 10 }} />
                  </div>
                </div>

                <div className="ai-config-card-desc">{meta.description}</div>

                {/* 测试结果 */}
                {result && (
                  <div className={`ai-config-test-result ${result.ok ? 'success' : result.skipped ? 'skipped' : 'error'}`}>
                    <i className={`fas fa-${result.ok ? 'check-circle' : result.skipped ? 'info-circle' : 'exclamation-circle'}`} />
                    {result.skipped
                      ? `跳过 · ${result.reason || '未配置'}`
                      : result.ok
                        ? `连接成功 · ${result.model} · ${result.response || 'OK'}`
                        : `连接失败 · ${result.error}`
                    }
                    {result.elapsed_ms != null && <span style={{ marginLeft: 'auto', opacity: 0.6 }}>{result.elapsed_ms}ms</span>}
                  </div>
                )}

                {/* 展开编辑区 */}
                {isExpanded && (
                  <div className="ai-config-card-body">
                    <div className="form-group">
                      <label className="form-check">
                        <input type="checkbox" checked={ep.enabled}
                          onChange={e => handleSaveEndpoint(key, { enabled: e.target.checked })} />
                        <span className="form-check-label">启用此入口</span>
                      </label>
                    </div>

                    <div className="form-group">
                      <label className="form-label"><i className="fas fa-link" /> API 地址</label>
                      <input className="form-control" value={ep.base_url || ''}
                        onChange={e => handleSaveEndpoint(key, { base_url: e.target.value })}
                        placeholder="https://api.deepseek.com" />
                    </div>

                    <div className="form-group">
                      <label className="form-label"><i className="fas fa-key" /> API Key</label>
                      <div className="ai-config-key-row">
                        <input className="form-control"
                          type={showApiKey[key] ? 'text' : 'password'}
                          value={showApiKey[key] ? (ep.api_key === '***' ? '' : ep.api_key || '') : (ep.api_key || '')}
                          onChange={e => handleSaveEndpoint(key, { api_key: e.target.value })}
                          placeholder={ep.api_key === '***' ? '已配置 (***' : 'sk-...'} />
                        <button className="btn btn-secondary"
                          onClick={() => setShowApiKey(prev => ({ ...prev, [key]: !prev[key] }))}
                          style={{ padding: '6px 10px', fontSize: 11 }}>
                          <i className={`fas fa-${showApiKey[key] ? 'eye-slash' : 'eye'}`} />
                        </button>
                      </div>
                      <div className="form-text">留空则跳过此入口。保存后 Key 以 *** 掩码显示。</div>
                    </div>

                    <div className="form-group">
                      <label className="form-label"><i className="fas fa-robot" /> 模型</label>
                      <input className="form-control" value={ep.model || ''}
                        onChange={e => handleSaveEndpoint(key, { model: e.target.value })}
                        placeholder="deepseek-v4-flash" />
                    </div>

                    {/* 高级参数折叠区 */}
                    <details className="ai-config-advanced">
                      <summary>高级参数</summary>
                      <div className="ai-config-advanced-body">
                        {ep.enable_thinking !== undefined && (
                          <div className="form-group">
                            <label className="switch-row">
                              <input type="checkbox" checked={ep.enable_thinking}
                                onChange={e => handleSaveEndpoint(key, { enable_thinking: e.target.checked })} />
                              <span>启用深度思考</span>
                            </label>
                          </div>
                        )}
                        {ep.thinking_budget !== undefined && (
                          <div className="form-group">
                            <label className="form-label">思维预算 token</label>
                            <input className="form-control" type="number" min={128} max={32768}
                              value={ep.thinking_budget}
                              onChange={e => handleSaveEndpoint(key, { thinking_budget: Number(e.target.value) })} />
                          </div>
                        )}
                        {ep.deep_thinking_max_tokens !== undefined && (
                          <div className="form-group">
                            <label className="form-label">深度输出上限 token</label>
                            <input className="form-control" type="number" min={1024}
                              value={ep.deep_thinking_max_tokens}
                              onChange={e => handleSaveEndpoint(key, { deep_thinking_max_tokens: Number(e.target.value) })} />
                          </div>
                        )}
                        {ep.json_response_format !== undefined && (
                          <div className="form-group">
                            <label className="switch-row">
                              <input type="checkbox" checked={ep.json_response_format}
                                onChange={e => handleSaveEndpoint(key, { json_response_format: e.target.checked })} />
                              <span>强制 JSON 输出</span>
                            </label>
                          </div>
                        )}
                        {ep.target_lang !== undefined && (
                          <div className="form-group">
                            <label className="form-label">目标语言</label>
                            <input className="form-control" value={ep.target_lang || 'zh-CN'}
                              onChange={e => handleSaveEndpoint(key, { target_lang: e.target.value })} />
                          </div>
                        )}
                        {ep.max_tokens !== undefined && (
                          <div className="form-group">
                            <label className="form-label">最大输出 token</label>
                            <input className="form-control" type="number" min={1024}
                              value={ep.max_tokens}
                              onChange={e => handleSaveEndpoint(key, { max_tokens: Number(e.target.value) })} />
                          </div>
                        )}
                      </div>
                    </details>

                    {/* 从其他入口导入 */}
                    <div className="ai-config-import-row">
                      <button className="btn btn-secondary"
                        onClick={() => setShowImport(showImport === key ? null : key)}
                        style={{ fontSize: 11, padding: '4px 10px' }}>
                        <i className="fas fa-download" /> 从其他入口导入
                      </button>
                      {showImport === key && (
                        <div className="ai-config-import-panel">
                          <select className="form-select-sm" value={importSource}
                            onChange={e => setImportSource(e.target.value)}>
                            <option value="">选择源入口...</option>
                            {Object.keys(endpoints).filter(k => k !== key).map(k => (
                              <option key={k} value={k}>{ENDPOINT_META[k]?.name || k}</option>
                            ))}
                          </select>
                          <label className="form-check" style={{ fontSize: 11 }}>
                            <input type="checkbox" checked={importFields.base_url}
                              onChange={e => setImportFields(f => ({ ...f, base_url: e.target.checked }))} />
                            <span>API 地址</span>
                          </label>
                          <label className="form-check" style={{ fontSize: 11 }}>
                            <input type="checkbox" checked={importFields.api_key}
                              onChange={e => setImportFields(f => ({ ...f, api_key: e.target.checked }))} />
                            <span>API Key</span>
                          </label>
                          <label className="form-check" style={{ fontSize: 11 }}>
                            <input type="checkbox" checked={importFields.model}
                              onChange={e => setImportFields(f => ({ ...f, model: e.target.checked }))} />
                            <span>模型</span>
                          </label>
                          <label className="form-check" style={{ fontSize: 11 }}>
                            <input type="checkbox" checked={importFields.params}
                              onChange={e => setImportFields(f => ({ ...f, params: e.target.checked }))} />
                            <span>高级参数</span>
                          </label>
                          <button className="btn btn-primary"
                            onClick={() => handleImport(key)}
                            disabled={!importSource || importSource === key}
                            style={{ fontSize: 11, padding: '4px 10px' }}>
                            应用
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ))}

      {/* 说明 */}
      <div className="settings-card">
        <div className="card-header">
          <h3><i className="fas fa-info-circle" /> 说明</h3>
        </div>
        <div className="card-body">
          <div className="info-list">
            <div className="info-item"><i className="fas fa-check" /> 每个 AI 调用入口独立配置 endpoint / API Key / 模型</div>
            <div className="info-item"><i className="fas fa-check" /> 支持从其他入口导入配置（API 地址 / Key / 模型 / 参数）</div>
            <div className="info-item"><i className="fas fa-check" /> 导入配置仅改变编辑态，需点击「保存设置」后生效</div>
            <div className="info-item"><i className="fas fa-check" /> 统一测试入口验证所有启用模块并反馈每个入口的问题</div>
          </div>
        </div>
      </div>
    </div>
  );
}
