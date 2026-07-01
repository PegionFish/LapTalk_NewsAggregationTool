import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../../api/client';
import { useToast } from '../../contexts/ToastContext';
import type { AiEndpointConfig, AiEndpointTestResult, AiSettingsResponse } from '../../types';

// 统一使用 ``article_processing`` 作为主入口 key
const PRIMARY_ENDPOINT_KEY = 'article_processing';
const ALL_ENDPOINT_KEYS = ['title_filter', 'article_processing', 'event_pipeline'];

const ENDPOINT_LABELS: Record<string, string> = {
  title_filter: '标题初筛',
  article_processing: '文章处理',
  event_pipeline: '事件管线',
};

interface Props {}

export default function AISettings(_props: Props) {
  const { showToast } = useToast();
  const [aiSettings, setAiSettings] = useState<AiSettingsResponse | null>(null);
  const [testResult, setTestResult] = useState<AiEndpointTestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);
  const [workers, setWorkers] = useState(10);  // 默认值，加载后覆盖
  const workerTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 加载配置
  useEffect(() => {
    api.getAiSettings().then(resp => {
      setAiSettings(resp);
      if (resp.ai_workers != null) setWorkers(resp.ai_workers);
    }).catch(() => {});
  }, []);

  const endpoints = aiSettings?.ai_endpoints ?? {};
  const primaryConfig = endpoints[PRIMARY_ENDPOINT_KEY] as AiEndpointConfig | undefined;

  // 保存到所有入口（后端使用统一全局字段）
  const handleSaveField = useCallback(async (field: string, value: string | boolean | number) => {
    if (!aiSettings) return;
    const updatedEndpoints = { ...endpoints };
    for (const key of ALL_ENDPOINT_KEYS) {
      updatedEndpoints[key] = { ...updatedEndpoints[key], [field]: value };
    }
    try {
      const resp = await api.updateAiSettings({ ai_endpoints: updatedEndpoints });
      setAiSettings(resp);
    } catch (e) {
      console.error('保存失败:', e);
      showToast(`保存失败: ${(e as Error).message}`, 'error');
    }
  }, [aiSettings, endpoints, showToast]);

  // 测试连接
  const handleTestConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const resp = await api.testAiEndpoints(PRIMARY_ENDPOINT_KEY);
      const result = resp.results?.[0] ?? null;
      setTestResult(result);
      if (result?.ok) {
        showToast('连接成功', 'success');
      } else if (result?.skipped) {
        showToast(`跳过: ${result.reason || '未配置'}`, 'info');
      } else {
        showToast(`连接失败: ${result?.error || '未知错误'}`, 'error');
      }
    } catch (e) {
      console.error('测试失败:', e);
      showToast(`测试失败: ${(e as Error).message}`, 'error');
    }
    setTesting(false);
  };

  // worker 滑块 - onChange 即时更新本地状态
  const handleWorkerChange = (val: number) => {
    setWorkers(val);
  };

  // worker 滑块 - onMouseUp/onMouseLeave 发送请求（防抖）
  const commitWorker = useCallback((val: number) => {
    if (workerTimerRef.current) clearTimeout(workerTimerRef.current);
    workerTimerRef.current = setTimeout(() => {
      api.setAiWorkers(val).then(resp => {
        showToast(`并发 Worker 数已设为 ${resp.workers}`, 'success');
      }).catch(e => {
        showToast(`设置 Worker 数失败: ${(e as Error).message}`, 'error');
      });
    }, 300);
  }, [showToast]);

  return (
    <div className="settings-container">
      <div style={{ marginBottom: 20 }}>
        <h3 style={{ margin: '0 0 4px 0', fontSize: 16, fontWeight: 700 }}>
          <i className="fas fa-microchip" style={{ marginRight: 8, color: 'var(--accent)' }} />
          DeepSeek AI 配置
        </h3>
        <p style={{ margin: 0, fontSize: 12, color: 'var(--text-secondary)' }}>
          统一配置所有 AI 调用的 API 地址、密钥和模型。三段式入口（标题初筛 / 文章处理 / 事件管线）共享同一配置。
        </p>
      </div>

      {/* 统一配置卡片 */}
      <div className="ai-config-card">
        <div className="ai-config-card-body" style={{ padding: 20 }}>

          {/* API 地址 */}
          <div className="form-group">
            <label className="form-label"><i className="fas fa-link" /> API 地址</label>
            <input className="form-control"
              value={primaryConfig?.base_url || ''}
              onChange={e => handleSaveField('base_url', e.target.value)}
              placeholder="https://api.deepseek.com" />
          </div>

          {/* API Key */}
          <div className="form-group">
            <label className="form-label"><i className="fas fa-key" /> API Key</label>
            <div className="ai-config-key-row">
              <input className="form-control"
                type={showApiKey ? 'text' : 'password'}
                value={showApiKey ? (primaryConfig?.api_key === '***' ? '' : primaryConfig?.api_key || '') : (primaryConfig?.api_key || '')}
                onChange={e => handleSaveField('api_key', e.target.value)}
                placeholder={primaryConfig?.api_key === '***' ? '已配置 (***)' : 'sk-...'} />
              <button className="btn btn-secondary"
                onClick={() => setShowApiKey(prev => !prev)}
                style={{ padding: '6px 10px', fontSize: 11 }}>
                <i className={`fas fa-${showApiKey ? 'eye-slash' : 'eye'}`} />
              </button>
            </div>
            <div className="form-text">留空则跳过此入口。保存后 Key 以 *** 掩码显示。</div>
          </div>

          {/* 模型 */}
          <div className="form-group">
            <label className="form-label"><i className="fas fa-robot" /> 模型</label>
            <input className="form-control"
              value={primaryConfig?.model || ''}
              onChange={e => handleSaveField('model', e.target.value)}
              placeholder="deepseek-v4-flash" />
          </div>

          {/* 并发 Worker 滑块 */}
          <div className="form-group">
            <label className="form-label">
              <i className="fas fa-sliders-h" />{' '}
              并发 Worker: <strong>{workers}</strong>
              <span style={{ fontSize: 11, color: 'var(--text-secondary)', marginLeft: 8, fontWeight: 400 }}>
                (范围 1-50)
              </span>
            </label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ fontSize: 11, color: 'var(--text-secondary)', minWidth: 16 }}>1</span>
              <input type="range" min={1} max={50} step={1}
                value={workers}
                onChange={e => handleWorkerChange(Number(e.target.value))}
                onMouseUp={e => commitWorker(Number((e.target as HTMLInputElement).value))}
                onTouchEnd={e => commitWorker(Number((e.target as HTMLInputElement).value))}
                style={{ flex: 1, accentColor: 'var(--accent)' }} />
              <span style={{ fontSize: 11, color: 'var(--text-secondary)', minWidth: 16 }}>50</span>
            </div>
          </div>

          {/* 测试连接 + 当前状态 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 16 }}>
            <button className="btn btn-secondary" onClick={handleTestConnection} disabled={testing}
              style={{ fontSize: 12, padding: '6px 14px' }}>
              <i className={`fas fa-${testing ? 'spinner fa-spin' : 'plug'}`} />
              {' '}{testing ? '测试中...' : '测试连接'}
            </button>

            {testResult && (
              <div className={`ai-config-test-result ${testResult.ok ? 'success' : testResult.skipped ? 'skipped' : 'error'}`}
                style={{ margin: 0, flex: 1 }}>
                <i className={`fas fa-${testResult.ok ? 'check-circle' : testResult.skipped ? 'info-circle' : 'exclamation-circle'}`} />
                {testResult.skipped
                  ? `跳过 · ${testResult.reason || '未配置'}`
                  : testResult.ok
                    ? `连接成功 · ${testResult.model || ''}` + (testResult.elapsed_ms != null ? ` · ${testResult.elapsed_ms}ms` : '')
                    : `连接失败 · ${testResult.error}`
                }
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 三段式入口状态指示 */}
      <div style={{ marginTop: 16, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {ALL_ENDPOINT_KEYS.map(key => {
          const ep = endpoints[key] as AiEndpointConfig | undefined;
          if (!ep) return null;
          return (
            <div key={key}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '6px 12px', borderRadius: 6,
                background: 'var(--bg-secondary)', border: '1px solid var(--border)',
                fontSize: 11, color: 'var(--text-secondary)',
              }}>
              <i className="fas fa-circle"
                style={{
                  fontSize: 6,
                  color: ep.enabled ? 'var(--accent-tertiary)' : 'var(--text-muted)',
                }} />
              <span>{ENDPOINT_LABELS[key] || key}</span>
              <span style={{ color: ep.enabled ? 'var(--accent-tertiary)' : 'var(--text-muted)' }}>
                {ep.enabled ? '启用' : '禁用'}
              </span>
            </div>
          );
        })}
      </div>

      {/* 说明 */}
      <div className="settings-card" style={{ marginTop: 20 }}>
        <div className="card-header">
          <h3><i className="fas fa-info-circle" /> 说明</h3>
        </div>
        <div className="card-body">
          <div className="info-list">
            <div className="info-item"><i className="fas fa-check" /> 标题初筛 / 文章处理 / 事件管线 共享同一个 AI 配置</div>
            <div className="info-item"><i className="fas fa-check" /> 修改任一字段自动保存到所有入口</div>
            <div className="info-item"><i className="fas fa-check" /> 并发 Worker 数控制同时处理的文章数量，调高可加快批量处理速度</div>
          </div>
        </div>
      </div>
    </div>
  );
}
