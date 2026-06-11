import { useState, type FormEvent } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { Input, Button } from '../components/ui';

export default function Login() {
  const { login, register } = useAuth();
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      if (isRegister) {
        await register(username, password, displayName);
      } else {
        await login(username, password);
      }
    } catch (err) {
      setError((err as Error).message);
    }
    setSubmitting(false);
  };

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '100vh',
      background: 'var(--bg-primary)',
      padding: 20,
    }}>
      <div style={{
        width: '100%',
        maxWidth: 380,
      }}>
        {/* Logo */}
        <div style={{
          textAlign: 'center',
          marginBottom: 32,
        }}>
          <div style={{
            width: 64,
            height: 64,
            margin: '0 auto 16px',
            background: 'linear-gradient(135deg, rgba(0, 212, 255, 0.15), rgba(0, 255, 136, 0.1))',
            borderRadius: 16,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            border: '1px solid rgba(0, 212, 255, 0.2)',
          }}>
            <i className="fas fa-newspaper" style={{
              fontSize: 28,
              color: 'var(--accent)',
            }} />
          </div>
          <h1 style={{
            fontSize: 22,
            fontWeight: 700,
            color: 'var(--text-primary)',
            marginBottom: 8,
          }}>
            新闻知识聚合中心
          </h1>
          <p style={{
            fontSize: 13,
            color: 'var(--text-muted)',
          }}>
            {isRegister ? '创建新账户' : '登录以继续'}
          </p>
        </div>

        {/* 表单卡片 */}
        <form onSubmit={handleSubmit} style={{
          background: 'var(--bg-secondary)',
          borderRadius: 16,
          padding: 28,
          border: '1px solid var(--border)',
        }}>
          {error && (
            <div style={{
              background: 'rgba(229, 115, 115, 0.12)',
              color: 'var(--accent-red)',
              padding: '10px 14px',
              borderRadius: 8,
              fontSize: 12,
              marginBottom: 16,
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}>
              <i className="fas fa-exclamation-circle" />
              {error}
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {isRegister && (
              <div>
                <label style={{
                  display: 'block',
                  fontSize: 12,
                  color: 'var(--text-secondary)',
                  marginBottom: 6,
                }}>
                  显示名称（可选）
                </label>
                <Input
                  placeholder="输入显示名称"
                  value={displayName}
                  onChange={e => setDisplayName(e.target.value)}
                />
              </div>
            )}

            <div>
              <label style={{
                display: 'block',
                fontSize: 12,
                color: 'var(--text-secondary)',
                marginBottom: 6,
              }}>
                用户名
              </label>
              <Input
                placeholder="输入用户名"
                value={username}
                onChange={e => setUsername(e.target.value)}
                required
                minLength={3}
              />
            </div>

            <div>
              <label style={{
                display: 'block',
                fontSize: 12,
                color: 'var(--text-secondary)',
                marginBottom: 6,
              }}>
                密码
              </label>
              <Input
                type="password"
                placeholder="输入密码"
                value={password}
                onChange={e => setPassword(e.target.value)}
                required
                minLength={6}
              />
            </div>
          </div>

          <Button
            type="submit"
            variant="primary"
            loading={submitting}
            style={{ width: '100%', marginTop: 20, padding: '12px 20px' }}
          >
            {isRegister ? '注册' : '登录'}
          </Button>

          <button
            type="button"
            onClick={() => {
              setIsRegister(!isRegister);
              setError('');
            }}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--accent)',
              fontSize: 12,
              cursor: 'pointer',
              textAlign: 'center',
              width: '100%',
              marginTop: 16,
              padding: 8,
              transition: 'color var(--transition-fast)',
            }}
          >
            {isRegister ? '已有账户？去登录' : '没有账户？去注册'}
          </button>
        </form>
      </div>
    </div>
  );
}
