import { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';
import { api } from '../api/client';
import GeneralSettings from './settings/GeneralSettings';
import AISettings from './settings/AISettings';
import CacheSettings from './settings/CacheSettings';
import AdminSettings from './settings/AdminSettings';
import LogSettings from './settings/LogSettings';
import './settings/settings.css';

type Section = 'general' | 'ai' | 'cache' | 'admin' | 'logs';

interface SectionDef {
  key: Section;
  icon: string;
  label: string;
  group: string;
}

const SECTIONS: SectionDef[] = [
  { key: 'general', icon: 'fa-sliders-h',    label: '通用设置',   group: '系统' },
  { key: 'ai',      icon: 'fa-brain',        label: 'AI 服务',    group: 'AI 服务' },
  { key: 'cache',   icon: 'fa-archive',      label: '内容缓存',   group: '系统' },
  { key: 'admin',   icon: 'fa-users-cog',    label: '用户管理',   group: '管理' },
  { key: 'logs',    icon: 'fa-terminal',     label: '操作日志',   group: '管理' },
];

export default function Settings() {
  const { user } = useAuth();
  const { showToast } = useToast();
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
  const [pipelineStatus, setPipelineStatus] = useState<{ running: boolean; total: number; done: number; failed: number; current: string; log: string[] }>({ running: false, total: 0, done: 0, failed: 0, current: '', log: [] });

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
      setPipelineEnabled(s.pipeline_schedule_enabled !== false);
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
        pipeline_schedule_enabled: pipelineEnabled,
        content_cache_path: cachePath,
        proxy_enabled: proxyEnabled,
        proxy_url: proxyUrl,
      });
      setMessage('配置已保存');
      showToast('配置已保存', 'success');
    } catch (e) {
      setMessage('保存失败: ' + (e as Error).message);
      showToast('保存失败: ' + (e as Error).message, 'error');
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
      showToast('抓取管道已启动', 'success');
    } catch (e) {
      setMessage('启动失败: ' + (e as Error).message);
      showToast('启动失败: ' + (e as Error).message, 'error');
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
        return <AISettings />;
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
