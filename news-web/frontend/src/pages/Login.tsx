import { useState, type FormEvent } from 'react';
import { useAuth } from '../contexts/AuthContext';

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
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      minHeight: '100vh', background: 'var(--bg-primary)',
    }}>
      <form onSubmit={handleSubmit} style={{
        background: 'var(--bg-secondary)', borderRadius: 12, padding: 32,
        width: 360, display: 'flex', flexDirection: 'column', gap: 16,
      }}>
        <h2 style={{ fontSize: 18, textAlign: 'center', color: 'var(--accent)' }}>
          {isRegister ? '注册账户' : '登录'}
        </h2>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', textAlign: 'center' }}>
          新闻知识聚合中心
        </div>

        {error && (
          <div style={{ background: 'rgba(229,115,115,0.15)', color: 'var(--accent-red)', padding: '8px 12px', borderRadius: 6, fontSize: 12 }}>
            {error}
          </div>
        )}

        {isRegister && (
          <input
            placeholder="显示名称（可选）"
            value={displayName}
            onChange={e => setDisplayName(e.target.value)}
            style={inputStyle}
          />
        )}

        <input
          placeholder="用户名"
          value={username}
          onChange={e => setUsername(e.target.value)}
          required
          minLength={3}
          style={inputStyle}
        />

        <input
          type="password"
          placeholder="密码"
          value={password}
          onChange={e => setPassword(e.target.value)}
          required
          minLength={6}
          style={inputStyle}
        />

        <button type="submit" disabled={submitting} style={{
          background: 'var(--accent)', border: 'none', borderRadius: 6,
          padding: '10px', color: '#000', fontWeight: 'bold', fontSize: 14,
          cursor: 'pointer', marginTop: 4,
        }}>
          {submitting ? '处理中...' : isRegister ? '注册' : '登录'}
        </button>

        <button type="button" onClick={() => setIsRegister(!isRegister)} style={{
          background: 'none', border: 'none', color: 'var(--accent)', fontSize: 12,
          cursor: 'pointer', textAlign: 'center',
        }}>
          {isRegister ? '已有账户？去登录' : '没有账户？去注册'}
        </button>
      </form>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6,
  padding: '10px 12px', color: 'var(--text-primary)', fontSize: 14, outline: 'none', width: '100%',
};
