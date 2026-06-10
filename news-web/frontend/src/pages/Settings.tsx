import { useEffect, useState } from 'react';
import { api } from '../api/client';

export default function Settings() {
  const [dbPath, setDbPath] = useState('');
  const [userAgent, setUserAgent] = useState('');
  const [openaiBaseUrl, setOpenaiBaseUrl] = useState('');
  const [openaiApiKey, setOpenaiApiKey] = useState('');
  const [openaiModel, setOpenaiModel] = useState('');
  const [pipelineEnabled, setPipelineEnabled] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    api.getSettings().then(s => {
      setDbPath(s.db_path || '');
      setUserAgent(s.user_agent || '');
      setOpenaiBaseUrl(s.openai_base_url || 'https://api.openai.com/v1');
      setOpenaiApiKey(s.openai_api_key || ''); // masked as '***' if set, else ''
      setOpenaiModel(s.openai_model || 'gpt-4o-mini');
      setPipelineEnabled(s.pipeline_schedule_enabled !== false);
    }).catch(() => {});
  }, []);

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
        pipeline_schedule_enabled: pipelineEnabled,
      });
      setMessage('已保存');
    } catch (e) {
      setMessage('保存失败: ' + (e as Error).message);
    }
    setSaving(false);
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6,
    padding: '8px 12px', color: 'var(--text-primary)', fontSize: 13, outline: 'none', marginTop: 4,
  };
  const labelStyle: React.CSSProperties = { fontSize: 13, color: 'var(--text-secondary)', marginTop: 16, display: 'block' };

  return (
    <div style={{ maxWidth: 600 }}>
      <h2 style={{ marginBottom: 20 }}>⚙ 设置</h2>

      <div style={{ background: 'var(--bg-secondary)', borderRadius: 10, padding: 20 }}>
        <h3 style={{ fontSize: 14, marginBottom: 8, color: 'var(--accent)' }}>数据库</h3>
        <label style={labelStyle}>
          📁 数据库路径
          <input value={dbPath} onChange={e => setDbPath(e.target.value)} placeholder="/path/to/news.db" style={inputStyle} />
        </label>
        <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 4 }}>支持本地路径或 NAS 共享挂载点</div>

        <h3 style={{ fontSize: 14, marginTop: 20, marginBottom: 8, color: 'var(--accent)' }}>AI 配置（OpenAI 兼容）</h3>
        <label style={labelStyle}>
          🔗 API 地址
          <input value={openaiBaseUrl} onChange={e => setOpenaiBaseUrl(e.target.value)} style={inputStyle} />
        </label>
        <label style={labelStyle}>
          🔑 API Key
          <input value={openaiApiKey} onChange={e => setOpenaiApiKey(e.target.value)} type="password" style={inputStyle} />
        </label>
        <label style={labelStyle}>
          🤖 模型
          <input value={openaiModel} onChange={e => setOpenaiModel(e.target.value)} style={inputStyle} />
        </label>
        <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 4 }}>支持 OpenAI、DeepSeek、Ollama 等兼容端点</div>

        <h3 style={{ fontSize: 14, marginTop: 20, marginBottom: 8, color: 'var(--accent)' }}>抓取调度</h3>
        <label style={{ ...labelStyle, flexDirection: 'row', display: 'flex', alignItems: 'center', gap: 8 }}>
          <input type="checkbox" checked={pipelineEnabled} onChange={e => setPipelineEnabled(e.target.checked)}
            style={{ width: 16, height: 16 }} />
          <span>启用定时抓取（每天 10:00 / 17:00）</span>
        </label>

        <h3 style={{ fontSize: 14, marginTop: 20, marginBottom: 8, color: 'var(--accent)' }}>网络</h3>
        <label style={labelStyle}>
          🌐 User-Agent
          <input value={userAgent} onChange={e => setUserAgent(e.target.value)} style={inputStyle} />
        </label>

        <button onClick={handleSave} disabled={saving}
          style={{ marginTop: 20, background: 'var(--accent)', border: 'none', borderRadius: 6, padding: '10px 24px', color: '#000', fontWeight: 'bold', fontSize: 14, cursor: 'pointer' }}>
          {saving ? '保存中...' : '保存设置'}
        </button>

        {message && <div style={{ marginTop: 12, fontSize: 13, color: 'var(--accent-green)' }}>{message}</div>}
      </div>
    </div>
  );
}
