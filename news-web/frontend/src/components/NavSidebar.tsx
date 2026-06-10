import { NavLink } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

const NAV_ITEMS = [
  { path: '/', label: '仪表盘', icon: '📊' },
  { path: '/workspace', label: '逻辑链工作台', icon: '🖱' },
  { path: '/articles', label: '文章检索', icon: '📄' },
  { path: '/chains', label: '逻辑链列表', icon: '📋' },
  { path: '/settings', label: '设置', icon: '⚙' },
];

export default function NavSidebar() {
  const { user, logout } = useAuth();

  return (
    <nav style={{
      width: 200, height: '100vh', background: 'var(--bg-secondary)',
      borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column', padding: '12px 0'
    }}>
      <div style={{ padding: '12px 16px', fontSize: 16, fontWeight: 'bold', color: 'var(--accent)', marginBottom: 8 }}>
        新闻知识聚合
      </div>

      {/* User info */}
      <div style={{ padding: '8px 16px', fontSize: 11, color: 'var(--text-secondary)', borderBottom: '1px solid var(--border)', marginBottom: 4 }}>
        {user?.display_name || user?.username}
        <span style={{ float: 'right', color: 'var(--accent)' }}>{user?.role === 'admin' ? '👑' : '👤'}</span>
      </div>

      {NAV_ITEMS.map(item => (
        <NavLink
          key={item.path}
          to={item.path}
          end={item.path === '/'}
          style={({ isActive }) => ({
            display: 'flex', alignItems: 'center', gap: 8, padding: '10px 16px',
            fontSize: 14, color: isActive ? 'var(--accent)' : 'var(--text-secondary)',
            background: isActive ? 'rgba(79,195,247,0.1)' : 'transparent',
            borderLeft: isActive ? '3px solid var(--accent)' : '3px solid transparent',
            textDecoration: 'none',
          })}
        >
          <span>{item.icon}</span>
          <span>{item.label}</span>
        </NavLink>
      ))}

      {/* Logout */}
      <div style={{ marginTop: 'auto', padding: '12px 16px', borderTop: '1px solid var(--border)' }}>
        <button onClick={logout} style={{
          background: 'var(--bg-card)', border: 'none', borderRadius: 4, padding: '6px 12px',
          color: 'var(--text-secondary)', fontSize: 12, cursor: 'pointer', width: '100%', textAlign: 'left',
        }}>
          🚪 退出登录
        </button>
      </div>
    </nav>
  );
}
