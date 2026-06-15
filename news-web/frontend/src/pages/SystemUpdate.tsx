import { useEffect, useState, useRef, useCallback } from 'react';
import { api } from '../api/client';
import type { UpdateVersion, UpdateManifest, UpdateStatus, BackupInfo } from '../types';
import { Card, Button, Badge, Loading } from '../components/ui';

type Phase = 'idle' | 'uploaded' | 'validating' | 'installing' | 'restarting' | 'done' | 'error';

const phaseLabels: Record<Phase, string> = {
  idle: '等待上传',
  uploaded: '已上传',
  validating: '校验中',
  installing: '安装中',
  restarting: '重启中',
  done: '完成',
  error: '错误',
};

const phaseColors: Record<Phase, string> = {
  idle: 'var(--text-muted)',
  uploaded: 'var(--accent)',
  validating: 'var(--accent-orange)',
  installing: 'var(--accent)',
  restarting: 'var(--accent-orange)',
  done: 'var(--accent-green)',
  error: 'var(--accent-red)',
};

export default function SystemUpdate() {
  const [currentVersion, setCurrentVersion] = useState<UpdateVersion | null>(null);
  const [updateStatus, setUpdateStatus] = useState<UpdateStatus | null>(null);
  const [backups, setBackups] = useState<BackupInfo[]>([]);

  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [manifest, setManifest] = useState<UpdateManifest | null>(null);
  const [uploading, setUploading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [skipBackup, setSkipBackup] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollTimer = useRef<ReturnType<typeof setInterval>>();

  // 加载初始数据
  useEffect(() => {
    api.getUpdateVersion().then(setCurrentVersion).catch(() => {});
    api.getUpdateStatus().then(setUpdateStatus).catch(() => {});
    api.listBackups().then(r => setBackups(r.backups)).catch(() => {});
  }, []);

  // 轮询更新状态
  const pollStatus = useCallback(async () => {
    try {
      const s = await api.getUpdateStatus();
      setUpdateStatus(s);
      if (s.phase === 'done' || s.phase === 'error') {
        clearInterval(pollTimer.current);
      }
    } catch {
      clearInterval(pollTimer.current);
    }
  }, []);

  // 处理文件选择
  const handleFileSelect = (file: File) => {
    if (!file.name.endsWith('.tar.gz')) {
      alert('请上传 .tar.gz 格式的更新包');
      return;
    }
    setUploadFile(file);
    setManifest(null);
  };

  // 上传
  const handleUpload = async () => {
    if (!uploadFile) return;
    setUploading(true);
    try {
      const res = await api.uploadUpdatePackage(uploadFile);
      setManifest(res.manifest);
      setUpdateStatus({ ...updateStatus!, phase: 'uploaded', manifest: res.manifest } as UpdateStatus);
    } catch (e) {
      alert('上传失败: ' + (e as Error).message);
    }
    setUploading(false);
  };

  // 应用更新
  const handleApply = async () => {
    if (!uploadFile) return;
    setApplying(true);
    setShowConfirm(false);
    try {
      await api.applyUpdate(uploadFile.name, skipBackup);
      // 开始轮询状态
      pollTimer.current = setInterval(pollStatus, 2000);
    } catch (e) {
      alert('应用失败: ' + (e as Error).message);
      setApplying(false);
    }
  };

  // 回滚
  const handleRollback = async (backupName: string) => {
    if (!confirm(`确定回滚到 ${backupName}？`)) return;
    try {
      await api.rollbackUpdate(backupName);
      pollTimer.current = setInterval(pollStatus, 2000);
    } catch (e) {
      alert('回滚失败: ' + (e as Error).message);
    }
  };

  // 拖拽
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFileSelect(file);
  };

  const phase = (updateStatus?.phase || 'idle') as Phase;
  const isBusy = phase === 'installing' || phase === 'restarting' || applying;

  return (
    <div style={{ padding: 24, overflow: 'auto', flex: 1 }}>
      {/* 标题 */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{
          fontSize: 20, fontWeight: 700, margin: 0,
          display: 'flex', alignItems: 'center', gap: 10,
        }}>
          <i className="fas fa-cloud-upload-alt" style={{ color: 'var(--accent)' }} />
          系统更新
        </h2>
      </div>

      {/* 当前版本 */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
        gap: 14, marginBottom: 24,
      }}>
        <StatBox icon="fa-code-branch" label="当前版本" value={currentVersion?.version || '—'} />
        <StatBox icon="fa-python" label="Python" value={currentVersion?.python_version || '—'} />
        <StatBox icon="fa-desktop" label="平台" value={currentVersion?.platform || '—'} />
        <StatBox icon="fa-clock" label="构建时间" value={currentVersion?.build_time ? formatTime(currentVersion.build_time) : '—'} />
      </div>

      {/* ═══ 上传区域 ═══ */}
      <Card flat style={{ padding: 20, marginBottom: 20 }}>
        <div style={{
          fontSize: 15, fontWeight: 600, marginBottom: 16,
          color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <i className="fas fa-file-upload" style={{ color: 'var(--accent)' }} />
          上传更新包
        </div>

        {/* 拖拽区 */}
        <div
          onDragOver={e => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          style={{
            border: `2px dashed ${dragOver ? 'var(--accent)' : 'var(--border)'}`,
            borderRadius: 12,
            padding: '40px 20px',
            textAlign: 'center',
            cursor: 'pointer',
            transition: 'all 0.2s',
            background: dragOver ? 'rgba(0, 212, 255, 0.05)' : 'transparent',
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".tar.gz"
            onChange={e => e.target.files?.[0] && handleFileSelect(e.target.files[0])}
            style={{ display: 'none' }}
          />
          <i className="fas fa-cloud-upload-alt" style={{
            fontSize: 36, color: dragOver ? 'var(--accent)' : 'var(--text-muted)',
            marginBottom: 12, display: 'block',
          }} />
          {uploadFile ? (
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
                {uploadFile.name}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
                {(uploadFile.size / 1024).toFixed(1)} KB
              </div>
            </div>
          ) : (
            <div>
              <div style={{ fontSize: 14, color: 'var(--text-secondary)' }}>
                拖拽更新包到这里，或点击选择文件
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
                支持 .tar.gz 格式
              </div>
            </div>
          )}
        </div>

        {/* 上传按钮 */}
        {uploadFile && !manifest && (
          <div style={{ marginTop: 16, display: 'flex', gap: 10 }}>
            <Button
              variant="primary"
              onClick={handleUpload}
              loading={uploading}
              disabled={uploading}
            >
              <i className="fas fa-upload" style={{ marginRight: 6 }} />
              上传并校验
            </Button>
            <Button
              variant="ghost"
              onClick={() => { setUploadFile(null); setManifest(null); }}
            >
              取消
            </Button>
          </div>
        )}
      </Card>

      {/* ═══ 更新包信息 ═══ */}
      {manifest && (
        <Card flat style={{ padding: 20, marginBottom: 20 }}>
          <div style={{
            fontSize: 15, fontWeight: 600, marginBottom: 16,
            color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 8,
          }}>
            <i className="fas fa-box" style={{ color: 'var(--accent-green)' }} />
            更新包信息
            <Badge variant="green">校验通过</Badge>
          </div>

          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: 12, marginBottom: 16,
          }}>
            <InfoRow label="版本" value={`v${manifest.version}`} />
            <InfoRow label="构建时间" value={formatTime(manifest.build_time)} />
            <InfoRow label="后端文件" value={`${manifest.backend_files.length} 个`} />
            <InfoRow label="前端文件" value={`${manifest.frontend_files.length} 个`} />
          </div>

          {/* 版本对比 */}
          <div style={{
            padding: '10px 14px', borderRadius: 8,
            background: 'rgba(0, 212, 255, 0.06)',
            border: '1px solid rgba(0, 212, 255, 0.15)',
            fontSize: 12, marginBottom: 16,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ color: 'var(--text-muted)' }}>当前:</span>
              <code style={{ color: 'var(--text-secondary)' }}>v{currentVersion?.version || '—'}</code>
              <i className="fas fa-arrow-right" style={{ color: 'var(--accent)', fontSize: 10 }} />
              <span style={{ color: 'var(--text-muted)' }}>目标:</span>
              <code style={{ color: 'var(--accent-green)', fontWeight: 600 }}>v{manifest.version}</code>
            </div>
          </div>

          {/* 应用按钮 */}
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <Button
              variant="green"
              onClick={() => setShowConfirm(true)}
              disabled={isBusy}
              loading={applying}
            >
              <i className="fas fa-download" style={{ marginRight: 6 }} />
              应用更新
            </Button>
            <Button
              variant="ghost"
              onClick={() => { setManifest(null); setUploadFile(null); }}
              disabled={isBusy}
            >
              取消
            </Button>
          </div>
        </Card>
      )}

      {/* ═══ 更新进度 ═══ */}
      {(isBusy || phase === 'done' || phase === 'error') && (
        <Card flat style={{ padding: 20, marginBottom: 20 }}>
          <div style={{
            fontSize: 15, fontWeight: 600, marginBottom: 16,
            color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 8,
          }}>
            <i className="fas fa-spinner" style={{
              color: phaseColors[phase],
              animation: isBusy ? 'spin 1s linear infinite' : 'none',
            }} />
            更新进度
            <Badge variant={phase === 'done' ? 'green' : phase === 'error' ? 'red' : 'blue'}>
              {phaseLabels[phase]}
            </Badge>
          </div>

          {/* 进度条 */}
          <div style={{
            height: 6, borderRadius: 3, background: 'var(--bg-card)',
            marginBottom: 16, overflow: 'hidden',
          }}>
            <div style={{
              height: '100%', borderRadius: 3,
              background: phase === 'error' ? 'var(--accent-red)' :
                          phase === 'done' ? 'var(--accent-green)' : 'var(--accent)',
              width: `${updateStatus?.progress || 0}%`,
              transition: 'width 0.5s ease',
            }} />
          </div>

          {/* 日志 */}
          <div style={{
            background: '#0d1117', borderRadius: 8,
            padding: '10px 12px', maxHeight: 240, overflowY: 'auto',
            fontFamily: 'var(--font-mono)', fontSize: 10, lineHeight: 1.8,
            border: '1px solid var(--border)',
          }}>
            {(updateStatus?.log || []).map((log, i) => (
              <div key={i} style={{
                color: log.includes('失败') || log.includes('错误') ? '#ef5350' :
                       log.includes('完成') || log.includes('成功') ? '#81c784' : '#90a4ae',
              }}>
                {log}
              </div>
            ))}
          </div>

          {phase === 'error' && (
            <div style={{
              marginTop: 12, padding: '10px 14px', borderRadius: 8,
              background: 'rgba(239, 83, 80, 0.08)',
              border: '1px solid rgba(239, 83, 80, 0.2)',
              fontSize: 12, color: 'var(--accent-red)',
            }}>
              <i className="fas fa-exclamation-circle" style={{ marginRight: 6 }} />
              {updateStatus?.error || '未知错误'}
            </div>
          )}
        </Card>
      )}

      {/* ═══ 备份列表 ═══ */}
      {backups.length > 0 && (
        <Card flat style={{ padding: 20 }}>
          <div style={{
            fontSize: 15, fontWeight: 600, marginBottom: 16,
            color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 8,
          }}>
            <i className="fas fa-history" style={{ color: 'var(--accent-orange)' }} />
            可用备份
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {backups.map(b => (
              <div key={b.name} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '10px 14px', borderRadius: 8,
                background: 'var(--bg-card)', border: '1px solid var(--border)',
              }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                    {b.name}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                    版本: v{b.version} · {b.created_at ? formatTime(b.created_at) : '—'}
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="xs"
                  onClick={() => handleRollback(b.name)}
                  disabled={isBusy}
                >
                  <i className="fas fa-undo" style={{ marginRight: 4 }} />
                  回滚
                </Button>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* ═══ 确认对话框 ═══ */}
      {showConfirm && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 1000,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'rgba(0, 0, 0, 0.6)', backdropFilter: 'blur(4px)',
        }}>
          <Card style={{ width: 440, padding: 24 }}>
            <div style={{ textAlign: 'center', marginBottom: 20 }}>
              <i className="fas fa-exclamation-triangle" style={{
                fontSize: 40, color: 'var(--accent-orange)', marginBottom: 12, display: 'block',
              }} />
              <h3 style={{ fontSize: 16, fontWeight: 700, margin: 0, color: 'var(--text-primary)' }}>
                确认更新系统？
              </h3>
              <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8 }}>
                更新过程中服务将短暂不可用。
                <br />
                建议保留备份以便回滚。
              </p>
            </div>

            <div style={{
              padding: '10px 14px', borderRadius: 8,
              background: 'rgba(0, 212, 255, 0.06)',
              border: '1px solid rgba(0, 212, 255, 0.15)',
              fontSize: 12, marginBottom: 16,
            }}>
              <div>v{currentVersion?.version || '—'} → v{manifest?.version || '—'}</div>
            </div>

            <label style={{
              display: 'flex', alignItems: 'center', gap: 8,
              fontSize: 12, color: 'var(--text-secondary)', marginBottom: 16, cursor: 'pointer',
            }}>
              <input
                type="checkbox"
                checked={skipBackup}
                onChange={e => setSkipBackup(e.target.checked)}
                style={{ accentColor: 'var(--accent)' }}
              />
              跳过备份（不推荐）
            </label>

            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <Button variant="ghost" onClick={() => setShowConfirm(false)}>
                取消
              </Button>
              <Button variant="green" onClick={handleApply}>
                <i className="fas fa-check" style={{ marginRight: 6 }} />
                确认更新
              </Button>
            </div>
          </Card>
        </div>
      )}

      {/* 动画样式 */}
      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}

function StatBox({ icon, label, value }: { icon: string; label: string; value: string }) {
  return (
    <div style={{
      padding: '12px 16px', borderRadius: 8,
      background: 'var(--bg-card)', border: '1px solid var(--border)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <i className={`fas ${icon}`} style={{ color: 'var(--accent)', fontSize: 11 }} />
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{label}</span>
      </div>
      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
        {value}
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0' }}>
      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{label}</span>
      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>{value}</span>
    </div>
  );
}

function formatTime(iso: string) {
  if (!iso) return '—';
  try {
    const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch {
    return iso.substring(0, 16).replace('T', ' ');
  }
}
