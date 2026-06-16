import { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { api } from '../api/client';
import GeneralSettings from './settings/GeneralSettings';
import AISettings from './settings/AISettings';
import TranslationSettings from './settings/TranslationSettings';
import CacheSettings from './settings/CacheSettings';
import AdminSettings from './settings/AdminSettings';
import LogSettings from './settings/LogSettings';
import './settings/settings.css';

type Section = 'general' | 'ai' | 'translation' | 'cache' | 'admin' | 'logs';

interface SectionDef {
  key: Section;
  icon: string;
  label: string;
  group: string;
}

const SECTIONS: SectionDef[] = [
  { key: 'general',     icon: 'fa-sliders-h',    label: '通用设置',   group: '系统' },
  { key: 'ai',          icon: 'fa-brain',        label: 'AI 分析',    group: 'AI 服务' },
  { key: 'translation', icon: 'fa-language',     label: 'AI 翻译',    group: 'AI 服务' },
  { key: 'cache',       icon: 'fa-archive',      label: '内容缓存',   group: '系统' },
  { key: 'admin',       icon: 'fa-users-cog',    label: '用户管理',   group: '管理' },
  { key: 'logs',        icon: 'fa-terminal',     label: '操作日志',   group: '管理' },
];

export default function Settings() {
  const { user } = useAuth();
  const [activeSection, setActiveSection] = useState<Section>('general');

  // 仅管理员可访问
  if (user?.role !== 'admin') {
    return <Navigate to="/" replace />;
  }

  // 通用设置
  const [dbPath, setDbPath] = useState('');
  const [userAgent, setUserAgent] = useState('');
  const [pipelineEnabled, setPipelineEnabled] = useState(true);
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineStatus, setPipelineStatus] = useState<{ last_run?: string | null; last_status?: string | null }>({});

  // AI 分析
  const [openaiBaseUrl, setOpenaiBaseUrl] = useState('');
  const [openaiApiKey, setOpenaiApiKey] = useState('');
  const [openaiModel, setOpenaiModel] = useState('');
  const [aiEnableThinking, setAiEnableThinking] = useState(true);
  const [aiThinkingBudget, setAiThinkingBudget] = useState(32768);
  const [aiDeepThinkingMaxTokens, setAiDeepThinkingMaxTokens] = useState(8192);
  const [aiJsonResponseFormat, setAiJsonResponseFormat] = useState(true);

  // 翻译
  const [translationEnabled, setTranslationEnabled] = useState(false);
  const [translationBaseUrl, setTranslationBaseUrl] = useState('');
  const [translationApiKey, setTranslationApiKey] = useState('');
  const [translationModel, setTranslationModel] = useState('');

  // 缓存
  const [cachePath, setCachePath] = useState('');

  // 代理
  const [proxyEnabled, setProxyEnabled] = useState(false);
  const [proxyUrl, setProxyUrl] = useState('');

  // 保存
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  // 加载配置
  useEffect(() => {
    api.getSettings().then(s => {
      setDbPath(s.db_path || '');
      setUserAgent(s.user_agent || '');
      setOpenaiBaseUrl(s.openai_base_url || 'https://api.openai.com/v1');
      setOpenaiApiKey(s.openai_api_key || '');
      setOpenaiModel(s.openai_model || 'deepseek-ai/DeepSeek-V3.2');
      setAiEnableThinking(s.ai_enable_thinking !== false);
      setAiThinkingBudget(Number(s.ai_thinking_budget || 32768));
      setAiDeepThinkingMaxTokens(Number(s.ai_deep_thinking_max_tokens || 8192));
      setAiJsonResponseFormat(s.ai_json_response_format !== false);
      setPipelineEnabled(s.pipeline_schedule_enabled !== false);
      setTranslationEnabled(s.translation_enabled === true);
      setTranslationBaseUrl(s.translation_base_url || 'https://api.siliconflow.cn/v1');
      setTranslationApiKey(s.translation_api_key || '');
      setTranslationModel(s.translation_model || 'deepseek-ai/DeepSeek-V3.2');
      setCachePath(s.content_cache_path || '');
      setProxyEnabled(s.proxy_enabled === true);
      setProxyUrl(s.proxy_url || '');
    }).catch(() => {});
    api.getPipelineStatus().then(s => setPipelineStatus(s)).catch(() => {});
  }, []);

  // 保存
  const handleSave = async () => {
    setSaving(true);
    setMessage('');
    try {
      await api.updateSettings({
        db_path: dbPath,
        user_agent: userAgent,
        openai_base_url: openaiBaseUrl,
        openai_api_key: openaiApiKey,
        openai_model: openaiModel,
        ai_enable_thinking: aiEnableThinking,
        ai_thinking_budget: aiThinkingBudget,
        ai_deep_thinking_max_tokens: aiDeepThinkingMaxTokens,
        ai_json_response_format: aiJsonResponseFormat,
        pipeline_schedule_enabled: pipelineEnabled,
        translation_enabled: translationEnabled,
        translation_base_url: translationBaseUrl,
        translation_api_key: translationApiKey,
        translation_model: translationModel,
        content_cache_path: cachePath,
        proxy_enabled: proxyEnabled,
        proxy_url: proxyUrl,
      });
      setMessage('配置已保存');
    } catch (e) {
      setMessage('保存失败: ' + (e as Error).message);
    }
    setSaving(false);
  };

  // 管道触发
  const pollPipelineStatus = async () => {
    for (let i = 0; i < 60; i++) {
      const s = await api.getPipelineStatus();
      setPipelineStatus(s);
      if (!s.running) { setPipelineRunning(false); return; }
      await new Promise(r => setTimeout(r, 2000));
    }
    setPipelineRunning(false);
  };

  const handleTriggerPipeline = async () => {
    if (pipelineRunning) return;
    setPipelineRunning(true);
    setMessage('');
    try {
      await api.triggerPipeline();
      pollPipelineStatus();
    } catch (e) {
      setMessage('启动失败: ' + (e as Error).message);
      setPipelineRunning(false);
    }
  };

  // 渲染当前活动面板
  const renderSection = () => {
    switch (activeSection) {
      case 'general':
        return <GeneralSettings
          dbPath={dbPath} setDbPath={setDbPath}
          userAgent={userAgent} setUserAgent={setUserAgent}
          pipelineEnabled={pipelineEnabled} setPipelineEnabled={setPipelineEnabled}
          pipelineRunning={pipelineRunning} pipelineStatus={pipelineStatus}
          onTriggerPipeline={handleTriggerPipeline}
          proxyEnabled={proxyEnabled} setProxyEnabled={setProxyEnabled}
          proxyUrl={proxyUrl} setProxyUrl={setProxyUrl}
        />;
      case 'ai':
        return <AISettings
          baseUrl={openaiBaseUrl} setBaseUrl={setOpenaiBaseUrl}
          apiKey={openaiApiKey} setApiKey={setOpenaiApiKey}
          model={openaiModel} setModel={setOpenaiModel}
          enableThinking={aiEnableThinking} setEnableThinking={setAiEnableThinking}
          thinkingBudget={aiThinkingBudget} setThinkingBudget={setAiThinkingBudget}
          deepThinkingMaxTokens={aiDeepThinkingMaxTokens} setDeepThinkingMaxTokens={setAiDeepThinkingMaxTokens}
          jsonResponseFormat={aiJsonResponseFormat} setJsonResponseFormat={setAiJsonResponseFormat}
        />;
      case 'translation':
        return <TranslationSettings
          enabled={translationEnabled} setEnabled={setTranslationEnabled}
          baseUrl={translationBaseUrl} setBaseUrl={setTranslationBaseUrl}
          apiKey={translationApiKey} setApiKey={setTranslationApiKey}
          model={translationModel} setModel={setTranslationModel}
        />;
      case 'cache':
        return <CacheSettings cachePath={cachePath} setCachePath={setCachePath} />;
      case 'admin':
        return <AdminSettings />;
      case 'logs':
        return <LogSettings />;
    }
  };

  // 获取当前节标题
  const currentSection = SECTIONS.find(s => s.key === activeSection)!;

  return (
    <div className="settings-layout">
      {/* 左侧导航 */}
      <aside className="settings-sidebar">
        <div className="sidebar-menu">
          {['系统', 'AI 服务', '管理'].map(group => (
            <div key={group} className="sidebar-section">
              <div className="sidebar-section-title"><i className="fas fa-circle" /> {group}</div>
              {SECTIONS.filter(s => s.group === group).map(s => (
                <div key={s.key}
                  className={`sidebar-item${activeSection === s.key ? ' active' : ''}`}
                  onClick={() => setActiveSection(s.key)}>
                  <i className={`fas ${s.icon}`} />
                  <span>{s.label}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </aside>

      {/* 右侧内容 */}
      <section className="settings-content">
        <div className="settings-section-header">
          <h2><i className={`fas ${currentSection.icon}`} /> {currentSection.label}</h2>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            {SECTIONS.findIndex(s => s.key === activeSection) + 1} / {SECTIONS.length}
          </div>
        </div>

        {renderSection()}

        {/* 保存按钮 */}
        <button className="btn-save" onClick={handleSave} disabled={saving}>
          <i className={`fas fa-${saving ? 'spinner fa-spin' : 'save'}`} />
          {saving ? '保存中...' : '保存设置'}
        </button>

        {message && (
          <div className={`save-message ${message.includes('失败') ? 'error' : 'success'}`}>
            <i className={`fas fa-${message.includes('失败') ? 'exclamation-circle' : 'check-circle'}`} />
            {message}
          </div>
        )}
      </section>
    </div>
  );
}
